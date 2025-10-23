import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from .models import WordChainGame, WordChainEntry

class WordChainConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.game_id = self.scope['url_route']['kwargs']['game_id']
        self.room_group_name = f'wordchain_{self.game_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send current game state
        game_state = await self.get_game_state()
        await self.send(text_data=json.dumps({
            'type': 'game_state',
            'data': game_state
        }))

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get('type')

        if message_type == 'request_state':
            game_state = await self.get_game_state()
            await self.send(text_data=json.dumps({
                'type': 'game_state',
                'data': game_state
            }))

    # Receive message from room group
    async def game_update(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'game_update',
            'data': event['data']
        }))

    @database_sync_to_async
    def get_game_state(self):
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
