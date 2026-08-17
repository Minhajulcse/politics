import os
import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'coup-secret-key-123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent', ping_timeout=60)

COUP_CARDS = [
    "ডিউক (Duke)", "ডিউক (Duke)", "ডিউক (Duke)",
    "গুপ্তঘাতক (Assassin)", "গুপ্তঘাতক (Assassin)", "গুপ্তঘাতক (Assassin)",
    "ক্যাপ্টেন (Captain)", "ক্যাপ্টেন (Captain)", "ক্যাপ্টেন (Captain)",
    "রাষ্ট্রদূত (Ambassador)", "রাষ্ট্রদূত (Ambassador)", "রাষ্ট্রদূত (Ambassador)",
    "কাউন্টেস (Contessa)", "কাউন্টেস (Contessa)", "কাউন্টেস (Contessa)"
]

rooms = {}

@app.route('/')
def index():
    return render_template('index.html')

def get_lobby_data(room_code):
    if room_code not in rooms: return {'players': [], 'host': None}
    room = rooms[room_code]
    return {
        'players': [{'name': p['name'], 'uid': uid, 'online': p['online']} for uid, p in room['players'].items()],
        'host': room['host_uid']
    }

def add_log(room_code, msg):
    rooms[room_code]['logs'].insert(0, msg)
    if len(rooms[room_code]['logs']) > 30:
        rooms[room_code]['logs'].pop()

def broadcast_game_state(room_code):
    room = rooms[room_code]
    public_players = []
    
    for uid, p in room['players'].items():
        public_players.append({
            'uid': uid,
            'name': p['name'],
            'coins': p['coins'],
            'hidden_cards_count': len(p['cards']),
            'revealed_cards': p['revealed_cards'],
            'is_dead': len(p['cards']) == 0 and len(p['revealed_cards']) > 0
        })
    
    current_turn_uid = None
    if room['status'] == 'playing' and len(room.get('turn_order', [])) > 0:
        current_turn_uid = room['turn_order'][room['turn_index']]

    public_state = {
        'players': public_players,
        'logs': room['logs'],
        'deck_count': len(room['deck']),
        'current_turn_uid': current_turn_uid
    }
    
    for uid, p in room['players'].items():
        if p['online']:
            emit('game_state_update', {
                'public': public_state,
                'private': {
                    'my_cards': p['cards'],
                    'my_coins': p['coins'],
                    'must_lose_card': p.get('must_lose_card', False)
                }
            }, to=p['sid'])

@socketio.on('create_room')
def handle_create(data):
    uid = data['uid']
    name = data['name']
    
    room_code = ''.join(random.choices(string.ascii_uppercase, k=4))
    while room_code in rooms:
        room_code = ''.join(random.choices(string.ascii_uppercase, k=4))
        
    rooms[room_code] = {
        'status': 'waiting',
        'host_uid': uid,
        'players': {},
        'deck': [],
        'logs': [],
        'turn_order': [],
        'turn_index': 0
    }
    
    join_room(room_code)
    rooms[room_code]['players'][uid] = {
        'name': name, 'sid': request.sid, 'online': True,
        'coins': 0, 'cards': [], 'revealed_cards': [], 'must_lose_card': False
    }
    
    emit('room_joined', {'room_code': room_code, 'uid': uid, 'is_host': True}, to=request.sid)
    emit('update_lobby', get_lobby_data(room_code), to=room_code)

@socketio.on('join_room')
def handle_join(data):
    uid = data['uid']
    name = data['name']
    room_code = data['room_code'].upper()
    
    if room_code not in rooms:
        emit('error', {'msg': 'রুম কোডটি ভুল বা গেমটি আর নেই!'}, to=request.sid)
        return
        
    room = rooms[room_code]
    
    if uid not in room['players'] and room['status'] != 'waiting':
        emit('error', {'msg': 'এই রুমে অলরেডি গেম চলছে!'}, to=request.sid)
        return
        
    join_room(room_code)
    
    if uid not in room['players']:
        room['players'][uid] = {'name': name, 'sid': request.sid, 'online': True, 'coins': 0, 'cards': [], 'revealed_cards': [], 'must_lose_card': False}
    else:
        room['players'][uid]['sid'] = request.sid
        room['players'][uid]['online'] = True
        
    if not room['host_uid'] or room['host_uid'] not in room['players']:
        room['host_uid'] = uid
        
    is_host = (room['host_uid'] == uid)
    emit('room_joined', {'room_code': room_code, 'uid': uid, 'is_host': is_host}, to=request.sid)
    
    if room['status'] == 'waiting':
        emit('update_lobby', get_lobby_data(room_code), to=room_code)
    else:
        emit('game_started', {}, to=request.sid)
        broadcast_game_state(room_code)

@socketio.on('start_game')
def handle_start(data):
    room_code = data['room_code']
    room = rooms[room_code]
    
    uids = list(room['players'].keys())
    if len(uids) < 2:
        emit('error', {'msg': 'কমপক্ষে ২ জন প্লেয়ার দরকার!'}, to=request.sid)
        return
        
    room['status'] = 'playing'
    room['deck'] = COUP_CARDS.copy()
    random.shuffle(room['deck'])
    room['turn_order'] = uids.copy()
    random.shuffle(room['turn_order'])
    room['turn_index'] = 0
    
    first_player = room['players'][room['turn_order'][0]]['name']
    room['logs'] = [f"🎲 গেম শুরু হয়েছে! প্রথম চাল <b>{first_player}</b> এর।"]
    
    for uid in uids:
        room['players'][uid]['coins'] = 2
        room['players'][uid]['cards'] = [room['deck'].pop(), room['deck'].pop()]
        room['players'][uid]['revealed_cards'] = []
        room['players'][uid]['must_lose_card'] = False
        
    emit('game_started', {}, to=room_code)
    broadcast_game_state(room_code)

@socketio.on('next_turn')
def handle_next_turn(data):
    room_code = data['room_code']
    room = rooms[room_code]
    
    for _ in range(len(room['turn_order'])):
        room['turn_index'] = (room['turn_index'] + 1) % len(room['turn_order'])
        next_uid = room['turn_order'][room['turn_index']]
        if len(room['players'][next_uid]['cards']) > 0:
            break
            
    next_player_name = room['players'][room['turn_order'][room['turn_index']]]['name']
    add_log(room_code, f"➡️ এখন <b>{next_player_name}</b> এর চাল।")
    broadcast_game_state(room_code)

# --- Challenge System ---
@socketio.on('execute_challenge')
def handle_challenge(data):
    room_code = data['room_code']
    uid = data['uid'] # Challenger
    target_uid = data['target_uid']
    claimed_char = data['claimed_character']
    
    room = rooms[room_code]
    challenger = room['players'][uid]
    target = room['players'][target_uid]
    
    emit('play_alert', {'msg': f"🚨 {challenger['name']} চ্যালেঞ্জ করেছে {target['name']} কে!"}, to=room_code)
    
    has_card = False
    card_index = -1
    for i, c in enumerate(target['cards']):
        if c == claimed_char:
            has_card = True
            card_index = i
            break
            
    if has_card:
        # Target Wins, Challenger Loses
        add_log(room_code, f"✅ <b>{target['name']}</b> প্রমাণ করেছে তার কাছে <b style='color:#f1c40f;'>{claimed_char}</b> আছে! <b>{challenger['name']}</b> চ্যালেঞ্জ হেরেছে।")
        
        # Swap Target's Card
        swapped_card = target['cards'].pop(card_index)
        room['deck'].append(swapped_card)
        random.shuffle(room['deck'])
        target['cards'].append(room['deck'].pop())
        add_log(room_code, f"🔄 <b>{target['name']}</b> তার প্রমাণিত কার্ডটি ডেক-এ দিয়ে নতুন একটি কার্ড নিয়েছে।")
        
        # Enforce Penalty on Challenger
        challenger['must_lose_card'] = True
    else:
        # Bluff Caught! Target Loses
        add_log(room_code, f"❌ <b>{target['name']}</b> ব্লাফ দিচ্ছিল! তার কাছে <b style='color:#f1c40f;'>{claimed_char}</b> নেই। সে চ্যালেঞ্জ হেরেছে।")
        
        # Enforce Penalty on Target
        target['must_lose_card'] = True
        
    broadcast_game_state(room_code)

@socketio.on('reveal_card')
def handle_reveal(data):
    room_code = data['room_code']
    uid = data['uid']
    card_index = data['card_index']
    room = rooms[room_code]
    p = room['players'][uid]
    
    if 0 <= card_index < len(p['cards']):
        revealed_card = p['cards'].pop(card_index)
        p['revealed_cards'].append(revealed_card)
        p['must_lose_card'] = False # Penalty cleared
        
        add_log(room_code, f"💀 <b>{p['name']}</b> একটি কার্ড ফাঁস করেছে: <b style='color:#ff4d4d;'>{revealed_card}</b>!")
        if len(p['cards']) == 0:
            add_log(room_code, f"☠️ <b>{p['name']}</b> গেম থেকে বাদ পড়েছে!")
        broadcast_game_state(room_code)

@socketio.on('action_coin')
def handle_coin(data):
    room_code = data['room_code']
    uid = data['uid']
    amount = data['amount']
    action_name = data['action_name']
    room = rooms[room_code]
    p = room['players'][uid]
    
    if p['coins'] + amount < 0: return 
        
    p['coins'] += amount
    add_log(room_code, f"⚡ <b>{p['name']}</b> {action_name} করেছে।")
    broadcast_game_state(room_code)

@socketio.on('action_target')
def handle_action_target(data):
    room_code = data['room_code']
    uid = data['uid']
    target_uid = data['target_uid']
    amount = data['amount']
    action_name = data['action_name']
    
    room = rooms[room_code]
    p = room['players'][uid]
    target_p = room['players'][target_uid]
    
    if amount < 0 and p['coins'] + amount < 0: return 
    
    if action_name == 'ক্যাপ্টেনের চুরি':
        stolen = min(2, target_p['coins'])
        target_p['coins'] -= stolen
        p['coins'] += stolen
        add_log(room_code, f"🥷 <b>{p['name']}</b> ক্যাপ্টেন ব্যবহার করে <b>{target_p['name']}</b> এর কাছ থেকে {stolen} কয়েন চুরি করেছে!")
    else:
        p['coins'] += amount
        add_log(room_code, f"⚔️ <b>{p['name']}</b> <b>{target_p['name']}</b> এর উপর {action_name} করেছে!")
        
    broadcast_game_state(room_code)

@socketio.on('ambassador_draw')
def handle_ambassador_draw(data):
    room_code = data['room_code']
    uid = data['uid']
    room = rooms[room_code]
    p = room['players'][uid]
    
    draw_count = min(2, len(room['deck']))
    if draw_count > 0:
        drawn_cards = [room['deck'].pop() for _ in range(draw_count)]
        p['cards'].extend(drawn_cards)
        add_log(room_code, f"📜 <b>{p['name']}</b> রাষ্ট্রদূত (Ambassador) ব্যবহার করে ডেক থেকে ২টি কার্ড টেনেছে।")
        broadcast_game_state(room_code)

@socketio.on('ambassador_return')
def handle_ambassador_return(data):
    room_code = data['room_code']
    uid = data['uid']
    card_index = data['card_index']
    room = rooms[room_code]
    p = room['players'][uid]
    
    if 0 <= card_index < len(p['cards']):
        returned_card = p['cards'].pop(card_index)
        room['deck'].append(returned_card)
        random.shuffle(room['deck']) 
        add_log(room_code, f"🔄 <b>{p['name']}</b> একটি কার্ড ডেকে ফেরত দিয়েছে।")
        broadcast_game_state(room_code)

@socketio.on('leave_room_event')
def handle_leave_room(data):
    uid = data.get('uid')
    room_code = data.get('room_code')
    
    if room_code in rooms and uid in rooms[room_code]['players']:
        room = rooms[room_code]
        leave_room(room_code)
        if room['status'] == 'playing':
            room['players'][uid]['online'] = False
            room['players'][uid]['cards'] = [] 
            add_log(room_code, f"🚪 <b>{room['players'][uid]['name']}</b> গেম ছেড়ে চলে গেছে!")
            broadcast_game_state(room_code)
        else:
            del room['players'][uid]
            
        if room['host_uid'] == uid:
            if room['players']:
                room['host_uid'] = list(room['players'].keys())[0]
            else:
                del rooms[room_code]
                return
        emit('update_lobby', get_lobby_data(room_code), to=room_code)

@socketio.on('disconnect')
def handle_disconnect():
    for room_code, room in list(rooms.items()):
        for uid, p in list(room['players'].items()):
            if p.get('sid') == request.sid:
                p['online'] = False
                if room['status'] == 'waiting':
                    del room['players'][uid]
                emit('update_lobby', get_lobby_data(room_code), to=room_code)
                return

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
