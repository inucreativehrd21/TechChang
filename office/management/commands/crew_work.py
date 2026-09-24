"""
정비반이 작업 카드 하나를 맡아 PR 까지 끌고 간다.

  분류 → 관련 파일 수집 → 조사·패치 → worktree 적용 → 검증(check+test) → 브랜치 push → PR

검증에 실패하면 오류 출력을 그대로 물려 최대 2회까지 다시 고친다. 각 단계 결과는 Task 에 저장되므로
중간에 죽어도 같은 명령을 다시 실행하면 이어서 진행된다. 운영 코드와 서비스는 건드리지 않는다.

사용법:
  python manage.py crew_work --task 12
  python manage.py crew_work --task 12 --dry-run     # 패치까지만, push/PR 없음
  python manage.py crew_work --task 12 --retries 1
"""
import json

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from office import github, maintenance as M
from office.models import Task
from office.services import ask_agent, log


class Command(BaseCommand):
    help = '정비 작업 카드를 패치·검증하고 PR 을 생성합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--task', type=int, required=True)
        parser.add_argument('--dry-run', action='store_true', help='push·PR 없이 패치·검증까지만')
        parser.add_argument('--retries', type=int, default=2, help='검증 실패 시 재수정 횟수')
        parser.add_argument('--by', default='', help='지시한 관리자 username')

    def handle(self, *args, **opts):
        task = Task.objects.filter(pk=opts['task']).first()
        if task is None:
            raise CommandError(f"작업 #{opts['task']} 없음")
        if task.status in (Task.ST_PR, Task.ST_DONE):
            raise CommandError('이미 PR 이 열렸거나 완료된 작업입니다.')

        out = self.stdout.write
        by = User.objects.filter(username=opts['by']).first() if opts['by'] else None

        def rec(agent, action, text):
            out(f'  [{agent}] {text[:110]}')
            log(agent, action, f'#{task.id} {text}')

        task.status = Task.ST_WORKING
        task.save(update_fields=['status'])
        rec('lead', 'crew', f'정비 작업 착수: {task.title}')

        wt = branch = None
        try:
            # 1) 분류 (이미 했으면 재사용)
            if not task.triage:
                M.step_triage(task)
            rec('coding', 'triage', f"분류 {task.priority}/{task.kind} — {task.triage.get('summary', '')[:80]}")

            # 2) 관련 파일
            if not task.hints:
                task.hints = M.collect_hints(task)
                task.save(update_fields=['hints'])
            rec('coding', 'scan', f"관련 파일 {len(task.hints)}개: {', '.join(task.hints[:4])}")

            # 3) worktree
            wt, branch, err = M.make_worktree(task)
            if not wt:
                raise RuntimeError(f'worktree 생성 실패: {err}')
            task.branch = branch
            task.save(update_fields=['branch'])

            # 4) 패치 → 검증 (실패하면 오류를 물려 재시도)
            feedback = ''
            ok = False
            plan = {}
            for attempt in range(opts['retries'] + 1):
                task.attempts = attempt + 1
                prompt = M.PATCH_PROMPT.format(
                    title=task.title, body=task.body or '(없음)',
                    risk=(task.triage or {}).get('risk', '없음'),
                    files=M.read_files(task.hints), feedback=feedback, max_files=M.MAX_FILES)
                plan = M.parse_patch(ask_agent('coding', prompt, max_tokens=12000))

                if not plan.get('is_code_issue', True) or not plan.get('edits'):
                    task.plan = plan
                    task.result = {'plan': True, 'edits': 0, 'verify': None}
                    task.status = Task.ST_BACKLOG
                    task.note = '코드 문제가 아님 — 운영 조치 필요'[:300]
                    task.save()
                    rec('coding', 'crew', f"코드 문제 아님으로 판단: {plan.get('root_cause', '')[:120]}")
                    if task.issue_number:
                        github.comment_issue(task.issue_number,
                                             f"### 정비반 조사 결과\n\n{plan.get('root_cause', '')}\n\n"
                                             '코드 수정 대상이 아니라고 판단했습니다. 운영 조치를 검토해 주세요.')
                    return

                files, errs = M.apply_edits(wt, plan['edits'])
                rec('coding', 'patch', f"{attempt + 1}차 수정: {len(files)}개 파일"
                    + (f" (거부/실패 {len(errs)}건)" if errs else ''))
                if not files:
                    feedback = ('[직전 시도 실패]\n' + '\n'.join(errs) +
                                '\n위 문제를 고쳐서 edits 를 다시 만드세요. find 는 파일 원문 그대로여야 합니다.\n\n')
                    M.run(['git', 'checkout', '--', '.'], cwd=wt)
                    continue

                vok, vout = M.verify(wt)
                rec('lead', 'verify', f"{attempt + 1}차 검증 {'통과' if vok else '실패'}")
                if vok:
                    ok = True
                    task.plan = plan
                    task.result = {'plan': True, 'edits': len(files), 'files': files,
                                   'verify': vout[-1200:], 'errors': errs}
                    break
                feedback = ('[직전 시도 검증 실패 — 아래 오류를 반드시 해결하세요]\n' + vout[-2500:] +
                            '\n\n같은 작업을 다시, 이번엔 오류가 나지 않게 수정하세요.\n\n')
                M.run(['git', 'checkout', '--', '.'], cwd=wt)

            if not ok:
                task.plan = plan
                task.result = {'plan': True, 'edits': 0, 'verify': feedback[-1500:]}
                task.status = Task.ST_FAILED
                task.note = '검증 실패 — 운영자 확인 필요'
                task.save()
                rec('lead', 'fail', '검증을 통과하지 못해 중단 — 운영자 확인 필요')
                return

            if opts['dry_run']:
                task.status = Task.ST_APPROVED
                task.save()
                out(self.style.WARNING(f'[dry-run] 패치·검증까지 완료. worktree: {wt}'))
                out(json.dumps(plan.get('edits', []), ensure_ascii=False)[:1500])
                return

            # 5) push + PR
            pushed, perr = M.commit_push(wt, branch, task, task.result.get('files', []))
            if not pushed:
                task.status = Task.ST_FAILED
                task.note = perr[:300]
                task.save()
                rec('lead', 'fail', f'push 실패: {perr}')
                return

            body = plan.get('pr_body') or plan.get('root_cause', '')
            body += f"\n\n---\n검증: `manage.py check` + `manage.py test` 통과 (정비반 자동 실행)\n"
            if plan.get('migration_needed'):
                body += '\n⚠️ 모델 변경 — 배포 시 `migrate` 필요\n'
            if task.issue_number:
                body += f'\nCloses #{task.issue_number}\n'
            body += f'\n작업 카드 #{task.id} · 시도 {task.attempts}회\n'
            pr, perr = github.create_pr(branch, f'fix: {task.title[:80]}', body)
            if pr:
                task.pr_url = pr.get('html_url', '')
                task.status = Task.ST_PR
                rec('lead', 'pr', f"PR 생성: {task.pr_url}")
            else:
                task.status = Task.ST_FAILED
                task.note = f'PR 생성 실패: {perr}'[:300]
                rec('lead', 'fail', f'PR 생성 실패: {perr}')
            task.decided_by = by or task.decided_by
            task.decided_at = timezone.now()
            task.save()
            out(self.style.SUCCESS(f'완료: {task.pr_url or task.note}'))

        except Exception as ex:  # noqa: BLE001
            task.status = Task.ST_FAILED
            task.note = str(ex)[:300]
            task.save(update_fields=['status', 'note'])
            log('lead', 'fail', f'#{task.id} 정비 실패: {str(ex)[:200]}')
            raise
        finally:
            if wt:
                M.run(['git', 'worktree', 'remove', '--force', wt])
