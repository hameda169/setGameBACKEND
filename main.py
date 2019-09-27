from flask import Flask, request
from flask_socketio import SocketIO, send, join_room, leave_room, emit
from flask_pymongo import PyMongo
from flask_cors import CORS
from random import shuffle
from numpy import base_repr as br
import conf
from hashlib import md5
from time import time

app = Flask(__name__)
app.config['SECRET_KEY'] = conf.secret
app.config["MONGO_URI"] = conf.mongo
my_mongodb = PyMongo(app)
cors = CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")


# my_cards = list(range(1, 82))
# active_cards = []
# wins = dict()
# restricted = ''
# shuffle(my_cards)
# # room = 'my_room'
# my_room = []


def match_cards(*c):
    return all(map(lambda i: len({c[0][i], c[1][i], c[2][i]}) in [1, len(c)], range(len(c[0]))))


@app.route('/')
def hello():
    return 'Hello World'


@app.route('/room', methods=['POST'])
def add_room():
    name = request.json['name']
    id = f'{time()}'.encode()
    id = f'Room{md5(id).hexdigest()}'
    my_cards = list(range(1, 82))
    shuffle(my_cards)
    room = dict(name=name, id=id, my_cards=my_cards, active_cards=[], wins=dict(), restricted='',
                started=False, finished=False)
    my_mongodb.db.rooms.insert_one(room)
    return dict(type='createRoom_success', room=dict(name=name, id=id))


@app.route('/room/<room>')
def get_room(room):
    room = my_mongodb.db.rooms.find_one({'id': room})
    del room['_id'] if room else None
    return room if room else dict()


@socketio.on('join')
def my_connect(message):
    room = message['room']
    room = my_mongodb.db.rooms.find_one({'id': room})
    if not room or room['started']:
        emit('error', dict(message='Room is not exists or is closed'))
        return
    # user = dict(name=message['name'], room=room['id'], sid=f'{request.sid}')
    # my_mongodb.db.users.insert_one(user)
    wins = room['wins']
    print(f'received message from {request.sid}: ' + str(message))
    wins[f'{request.sid}'] = []
    join_room(room['id'])
    my_mongodb.db.rooms.update_one({'id': room['id']}, {'$set': {'wins': wins}})
    emit('join_success', dict(data=dict(id=f'{request.sid}')))


@socketio.on('startRoom')
def start_room(data):
    room = my_mongodb.db.rooms.find_one({'id': data['id']})
    my_cards = room['my_cards']
    active_cards = room['active_cards']
    my_cards, x = my_cards[:-6], my_cards[-6:]
    x = list(map(lambda y: f'000{br(y, base=3)}'[-4:], x))
    active_cards = [*active_cards, *x]
    my_mongodb.db.rooms.update_one({'id': data['id']},
                                   {'$set': {'my_cards': my_cards, 'active_cards': active_cards, 'started': True}})
    emit('init', dict(cards=x), room=room['id'])


@socketio.on('challenge')
def challenge(data):
    room = my_mongodb.db.rooms.find_one({'id': data['room'], f'wins.{request.sid}': {'$exists': True}})
    print(room)
    restricted = room['restricted']
    active_cards = room['active_cards']
    wins = room['wins']
    if request.sid == restricted:
        # TODO
        pass
    elif not list(set(data['cards']) - set(active_cards)) and match_cards(*data['cards']):
        restricted = ''
        active_cards = list(set(active_cards) - set(data['cards']))
        wins[f'{request.sid}'] = [*wins[f'{request.sid}'], *data['cards']]
        res = dict(cards=data['cards'], sid=f'{request.sid}', wins=wins)
        emit('challenge_success', res, room=room['id'])
    else:
        res = dict(cards=data['cards'], sid=f'{request.sid}')
        emit('challenge_fail', res, room=room['id'])
        restricted = request.sid
    my_mongodb.db.rooms.update_one({'id': room['id']},
                                   {'$set': {'restricted': restricted, 'active_cards': active_cards, 'wins': wins}})


@socketio.on('deal')
def deal(data):
    room = my_mongodb.db.rooms.find_one({'id': data['room'], f'wins.{request.sid}': {'$exists': True}})
    print(room)
    active_cards = room['active_cards']
    my_cards = room['my_cards']
    if len(active_cards) > 20:
        res = dict(type='DEAL_FAIL', message="Table has more than 20 cards")
        emit('deal_fail', res)
        return
    my_cards, x = my_cards[:-3], my_cards[-3:]
    x = list(map(lambda y: f'000{br(y, base=3)}'[-4:], x))
    active_cards = [*active_cards, *x]
    my_mongodb.db.rooms.update_one({'id': room['id']},
                                   {'$set': {'my_cards': my_cards, 'active_cards': active_cards}})
    res = dict(cards=x)
    emit('deal_success', res, room=room['id'], namespace='')


@socketio.on('connect')
def test_connect():
    print(f'Client {request.sid} Connected')


@socketio.on('disconnect')
def test_disconnect():
    rooms = my_mongodb.db.rooms.find({f'wins.{request.sid}': {'$exists': True}})
    print(rooms)
    [leave_room(i['id']) for i in rooms]
    print(f'Client {request.sid} disconnected')


if __name__ == '__main__':
    socketio.run(app)

"""
INIT            S->C(room)    
DEAL_REQUEST    C->S 
DEAL            S->C(room)
CHALLENGE       C->S
RESPONSE        S->C(room)
RESTRICT        S->C(single)
"""

"""
Tr Rc Ov
Rd Gr Bl
On Tw Th
Em Hf Fl
"""
