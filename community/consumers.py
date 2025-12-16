import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from django.utils import timezone
from .models import WordChainGame, WordChainEntry
import logging

logger = logging.getLogger(__name__)

class WordChainConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.game_id = self.scope['url_route']['kwargs']['game_id']
        self.room_group_name = f'wordchain_{self.game_id}'
        self.user = self.scope.get('user')

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        
        logger.info(f"[WebSocket] User connected to game {self.game_id}")

        # Send initial game state (한 번만)
        game_state = await self.get_game_state()
        await self.send(text_data=json.dumps({
            'type': 'initial_state',
            'data': game_state
        }))
        
        # 참가자들에게 새 플레이어 접속 알림 (Delta Update)
        if self.user and self.user.is_authenticated:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'player_connected',
                    'username': self.user.username,
                    'user_id': self.user.id
                }
            )

    async def disconnect(self, close_code):
        logger.info(f"[WebSocket] User disconnected from game {self.game_id}")
        
        # 참가자들에게 플레이어 퇴장 알림
        if self.user and self.user.is_authenticated:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'player_disconnected',
                    'username': self.user.username,
                    'user_id': self.user.id
                }
            )
        
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """클라이언트로부터 메시지 수신"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'heartbeat':
                # Heartbeat 응답
                await self.send(text_data=json.dumps({
                    'type': 'heartbeat_ack',
                    'timestamp': timezone.now().isoformat()
                }))
            elif message_type == 'request_state':
                # 전체 상태 요청 (재동기화)
                game_state = await self.get_game_state()
                await self.send(text_data=json.dumps({
                    'type': 'initial_state',
                    'data': game_state
                }))
        except Exception as e:
            logger.error(f"[WebSocket] Error in receive: {e}")

    # === Delta Update 이벤트 핸들러들 ===
    
    async def game_update(self, event):
        """일반 게임 업데이트 - Delta만 전송"""
        await self.send(text_data=json.dumps({
            'type': 'delta_update',
            'action': event['data'].get('action'),
            'data': event['data']
        }))
    
    async def player_connected(self, event):
        """플레이어 접속 알림"""
        await self.send(text_data=json.dumps({
            'type': 'player_connected',
            'username': event['username'],
            'user_id': event['user_id']
        }))
    
    async def player_disconnected(self, event):
        """플레이어 퇴장 알림"""
        await self.send(text_data=json.dumps({
            'type': 'player_disconnected',
            'username': event['username'],
            'user_id': event['user_id']
        }))

    @database_sync_to_async
    def get_game_state(self):
        """전체 게임 상태 조회 (초기 연결 시에만)"""
        try:
            game = WordChainGame.objects.get(id=self.game_id)
            
            # 참가자 목록
            participants_list = []
            for p in game.participants.all().order_by('id'):
                try:
                    display_name = p.profile.display_name
                except:
                    display_name = p.username
                participants_list.append({
                    'id': p.id,
                    'username': p.username,
                    'display_name': display_name,
                    'is_creator': p == game.creator
                })
            
            # 현재 턴 정보
            current_turn_info = None
            if game.current_turn:
                try:
                    current_turn_display = game.current_turn.profile.display_name
                except:
                    current_turn_display = game.current_turn.username
                current_turn_info = {
                    'id': game.current_turn.id,
                    'username': game.current_turn.username,
                    'display_name': current_turn_display
                }
            
            # 게임 시작 이후의 마지막 엔트리
            last_entry_info = None
            if game.start_date:
                active_entries = game.entries.filter(create_date__gte=game.start_date).order_by('-create_date')
                last_entry = active_entries.first()
                if last_entry:
                    try:
                        author_display = last_entry.author.profile.display_name
                    except:
                        author_display = last_entry.author.username
                    last_entry_info = {
                        'word': last_entry.word,
                        'author': last_entry.author.username,
                        'author_display': author_display,
                        'create_date': last_entry.create_date.isoformat()
                    }
            
            return {
                'success': True,
                'game': {
                    'id': game.id,
                    'title': game.title,
                    'status': game.status,
                    'participant_count': game.participants.count(),
                    'max_participants': game.max_participants,
                    'total_entries': game.entries.count(),
                    'last_word': game.last_word,
                    'expected_first_char': game.expected_first_char,
                    'current_turn': current_turn_info,
                    'start_date': game.start_date.isoformat() if game.start_date else None,
                },
                'participants': participants_list,
                'last_entry': last_entry_info
            }
        except WordChainGame.DoesNotExist:
            return {'success': False, 'error': 'Game not found'}



class TicTacToeConsumer(AsyncWebsocketConsumer):
    """틱택토 게임용 WebSocket Consumer"""
    
    async def connect(self):
        self.game_id = self.scope['url_route']['kwargs']['game_id']
        self.room_group_name = f'tictactoe_{self.game_id}'
        self.user = self.scope.get('user')

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        logger.info(f"[TicTacToe WS] User connected to game {self.game_id}")

        # Send initial state
        if self.user and self.user.is_authenticated:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'player_connected',
                    'username': self.user.username,
                    'user_id': self.user.id
                }
            )

    async def disconnect(self, close_code):
        logger.info(f"[TicTacToe WS] User disconnected from game {self.game_id}")
        
        if self.user and self.user.is_authenticated:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'player_disconnected',
                    'username': self.user.username,
                    'user_id': self.user.id
                }
            )
        
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """클라이언트로부터 메시지 수신"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'heartbeat':
                await self.send(text_data=json.dumps({
                    'type': 'heartbeat_ack',
                    'timestamp': timezone.now().isoformat()
                }))
        except Exception as e:
            logger.error(f"[TicTacToe WS] Error in receive: {e}")

    # Delta Update 이벤트 핸들러
    async def game_update(self, event):
        """게임 업데이트 - Delta만 전송"""
        await self.send(text_data=json.dumps({
            'type': 'delta_update',
            'action': event['data'].get('action'),
            'data': event['data']
        }))
    
    async def player_connected(self, event):
        """플레이어 접속 알림"""
        await self.send(text_data=json.dumps({
            'type': 'player_connected',
            'username': event['username'],
            'user_id': event['user_id']
        }))
    
    async def player_disconnected(self, event):
        """플레이어 퇴장 알림"""
        await self.send(text_data=json.dumps({
            'type': 'player_disconnected',
            'username': event['username'],
            'user_id': event['user_id']
        }))
