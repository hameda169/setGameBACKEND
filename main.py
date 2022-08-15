from flask import Flask, request
from flask_socketio import SocketIO, join_room, leave_room, emit, Namespace
from flask_pymongo import PyMongo
from flask_cors import CORS
from random import shuffle
from numpy import base_repr as br
from hashlib import md5
from time import time
from dotenv import load_dotenv
import os

load_dotenv('.env')

app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET')
app.config["MONGO_URI"] = os.getenv('MONGODB_URL')

my_mongodb = PyMongo(app)

CORS(app)

socketio = SocketIO(app, cors_allowed_origins="*")


def match_cards(*c):
    return all(map(lambda i: len({c[0][i], c[1][i], c[2][i]}) in [1, len(c)], range(len(c[0]))))


class MyGame(Namespace):
    @staticmethod
    def on_join(message):
        room = message['room']
        room = my_mongodb.db.rooms.find_one({'id': room, 'started': False},
                                            {'_id': 0, 'name': 1, 'started': 1, 'users': 1, 'id': 1})
        if not room:
            print(f'ERR on join user #{request.sid} to #{message["room"]}')
            emit('error', dict(signal='join', message='Room is not exists or is closed'))
            return
        users = room['users']
        print(f'user {request.sid} wants to join to {room["id"]}')
        users[request.sid] = dict(id=len(users), scores=[], name=message['name'])
        join_room(room['id'])
        my_mongodb.db.rooms.update_one({'id': room['id']}, {'$set': {'users': users}})
        print(f'user {request.sid} joined to {room["id"]} Successfully')
        emit('join_success', dict(id=users[request.sid]['id'], sid=request.sid, room_name=room['name']))

    @staticmethod
    def on_start_room(data):
        room = my_mongodb.db.rooms.find_one(
            {'id': data['id'], 'started': False, f'users.{request.sid}': {'$exists': True}},
            {'my_cards': 1, 'active_cards': 1, 'id': 1})
        if not room:
            print(f'ERR on start_room #{data["id"]} by user #{request.sid}')
            emit('error',
                 dict(signal='start_room', message='Room is not exists or is closed or you are not in this room'))
            return
        print(f'user {request.sid} is starting {room["id"]}')
        my_cards = room['my_cards']
        active_cards = room['active_cards']
        my_cards, x = my_cards[:-6], my_cards[-6:]
        x = list(map(lambda y: f'000{br(y, base=3)}'[-4:], x))
        active_cards = [*active_cards, *x]
        my_mongodb.db.rooms.update_one({'id': room['id']},
                                       {'$set': {'my_cards': my_cards, 'active_cards': active_cards, 'started': True}})
        print(f'{room["id"]} started by user {request.sid} Successfully')
        emit('init', dict(cards=x), room=room['id'])

    @staticmethod
    def on_challenge(data):
        room = my_mongodb.db.rooms.find_one(
            {'id': data['room'], 'started': True, f'users.{request.sid}': {'$exists': True}})
        if not room:
            print(f'ERR on challenge #{data["id"]} by user #{request.sid}')
            emit('error',
                 dict(signal='challenge', message='Room is not exists or is closed or you are not in this room'))
            return
        restricted = room['restricted']
        active_cards = room['active_cards']
        users = room['users']
        print(f'user {request.sid} wants to challenge cards')
        if request.sid == restricted:
            res = dict(cards=data['cards'], sid=request.sid)
            print(f'challenge rejected. user {request.sid} is restricted')
            emit('challenge_fail', res, room=room['id'])
        elif not list(set(data['cards']) - set(active_cards)) and match_cards(*data['cards']):
            restricted = ''
            active_cards = list(set(active_cards) - set(data['cards']))
            users[request.sid]['scores'] = [*users[request.sid]['scores'], *data['cards']]
            p_users = {x['id']: dict(scores=x['scores'], name=x['name']) for x in users.values()}
            res = dict(cards=data['cards'], id=users[request.sid]['id'], users=p_users)
            my_mongodb.db.rooms.update_one({'id': room['id']}, {
                '$set': {'restricted': restricted, 'active_cards': active_cards, 'users': users}})
            print(f'Challenge accepted from user {request.sid}. Cards {data["cards"]} set Successfully')
            emit('challenge_success', res, room=room['id'])
        else:
            res = dict(cards=data['cards'], id=users[request.sid]['id'])
            restricted = users[request.sid]['id']
            my_mongodb.db.rooms.update_one({'id': room['id']}, {'$set': {'restricted': restricted}})
            print(f'Challenge rejected. user {request.sid} is restricted or cards selected before')
            emit('challenge_fail', res, room=room['id'])

    @staticmethod
    def on_deal(data):
        room = my_mongodb.db.rooms.find_one(
            {'id': data['room'], 'started': True, f'users.{request.sid}': {'$exists': True}})
        if not room:
            print(f'ERR on deal #{data["id"]} by user #{request.sid}')
            emit('error', dict(signal='deal', message='Room is not exists or is closed or you are not in this room'))
            return
        print(f'Deal requested with user {request.sid} for room {room["id"]}')
        active_cards = room['active_cards']
        my_cards = room['my_cards']
        if len(active_cards) > 20:
            print(f'Deal failed. {room["id"]} has {len(active_cards)} cards')
            res = dict(type='DEAL_FAIL', message="Room has more than 20 cards")
            emit('deal_fail', res)
            return
        my_cards, x = my_cards[:-3], my_cards[-3:]
        x = list(map(lambda y: f'000{br(y, base=3)}'[-4:], x))
        active_cards = [*active_cards, *x]
        my_mongodb.db.rooms.update_one({'id': room['id']},
                                       {'$set': {'my_cards': my_cards, 'active_cards': active_cards}})
        print(f'Deal cards {x} to {room["id"]} is done Successfully')
        emit('deal_success', dict(cards=x), room=room['id'])

    @staticmethod
    def on_connect():
        print(f'Client {request.sid} Connected')

    @staticmethod
    def on_disconnect():
        rooms = my_mongodb.db.rooms.find({f'users.{request.sid}': {'$exists': True}})
        [leave_room(i['id']) for i in rooms]
        print(f'Client {request.sid} disconnected')


@app.route('/')
def hello():
    return 'Hello World. Version 1.1.0'


@app.route('/room', methods=['POST'])
def add_room():
    name = request.json['name']
    _id = f'{time()}'.encode()
    _id = f'Room{md5(_id).hexdigest()}'
    my_cards = list(range(1, 82))
    shuffle(my_cards)
    room = dict(name=name, id=_id, my_cards=my_cards, active_cards=[], users=dict(), restricted='', started=False,
                finished=False)
    my_mongodb.db.rooms.insert_one(room)
    return dict(type='createRoom_success', room=dict(name=name, id=_id))


@app.route('/room/<room>')
def get_room(room):
    room = my_mongodb.db.rooms.find_one({'id': room}, {'_id': 0, 'my_cards': 0})
    return room if room else dict()


socketio.on_namespace(MyGame(''))

if __name__ == '__main__':
    socketio.run(app)

"""
Tr Rc Ol
Rd Gr Bl
On Tw Th
Em Hf Fl
"""
