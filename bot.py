#!/usr/bin/env python3
"""
Telegram Verification Bot 
Features:
- Math verification for new users
- Message forwarding to admin
- Admin reply/block users
- Fraud detection
"""

import os
import json
import random
import asyncio
import sqlite3
import time
import logging
from aiohttp import web, ClientSession

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8324596212:ACHznhDgRuW2OcTYKAvFoa0UrDiMnef4Qyh')
ADMIN_UID = os.environ.get('ADMIN_UID', '1130431721')
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', 'W2OcTYKAvFoa0Ur')
PORT = int(os.environ.get('PORT', '25707'))
DOMAIN = os.environ.get('DOMAIN', '')  # For webhook
DB_PATH = os.environ.get('DB_PATH', 'bot_data.db')

NOTIFY_INTERVAL = 24 * 3600  # 1 day (seconds)
FRAUD_DB_URL = 'https://raw.githubusercontent.com/Squarelan/telegram-verify-bot/main/data/fraud.db'
NOTIFICATION_URL = 'https://raw.githubusercontent.com/Squarelan/telegram-verify-bot/main/data/notification.txt'
ENABLE_NOTIFICATION = False

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Database:
    """SQLite key-value store with TTL support"""
    
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT,
                expires_at INTEGER
            )
        ''')
        conn.commit()
        conn.close()
    
    def get(self, key):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT value, expires_at FROM kv_store WHERE key = ?', (key,))
        row = c.fetchone()
        conn.close()
        
        if row:
            value, expires_at = row
            if expires_at and time.time() > expires_at:
                self.delete(key)
                return None
            try:
                return json.loads(value)
            except:
                return value
        return None
    
    def put(self, key, value, ttl=None):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        expires_at = int(time.time() + ttl) if ttl else None
        value_str = json.dumps(value) if not isinstance(value, str) else value
        c.execute(
            'INSERT OR REPLACE INTO kv_store (key, value, expires_at) VALUES (?, ?, ?)',
            (key, value_str, expires_at)
        )
        conn.commit()
        conn.close()
    
    def delete(self, key):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('DELETE FROM kv_store WHERE key = ?', (key,))
        conn.commit()
        conn.close()


db = Database(DB_PATH)


# Telegram API functions
async def api_request(session, method, data=None):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/{method}'
    try:
        async with session.post(url, json=data) as resp:
            result = await resp.json()
            if not result.get('ok'):
                logger.error(f'API error: {result}')
            return result
    except Exception as e:
        logger.error(f'API request failed: {e}')
        return {'ok': False, 'error': str(e)}


async def send_message(session, chat_id, text, reply_markup=None):
    data = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        data['reply_markup'] = reply_markup
    return await api_request(session, 'sendMessage', data)


async def copy_message(session, chat_id, from_chat_id, message_id):
    return await api_request(session, 'copyMessage', {
        'chat_id': chat_id,
        'from_chat_id': from_chat_id,
        'message_id': message_id
    })


async def forward_message(session, chat_id, from_chat_id, message_id):
    return await api_request(session, 'forwardMessage', {
        'chat_id': chat_id,
        'from_chat_id': from_chat_id,
        'message_id': message_id
    })


async def edit_message_text(session, chat_id, message_id, text):
    return await api_request(session, 'editMessageText', {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text
    })


async def answer_callback_query(session, callback_query_id, text, show_alert=False):
    return await api_request(session, 'answerCallbackQuery', {
        'callback_query_id': callback_query_id,
        'text': text,
        'show_alert': show_alert
    })


# Math verification
def generate_math_problem():
    """Generate math problem with answer <= 100"""
    operators = ['+', '-', '*', '/']
    operator = random.choice(operators)
    
    if operator == '+':
        a = random.randint(1, 50)
        b = random.randint(1, 50)
        answer = a + b
    elif operator == '-':
        a = random.randint(1, 100)
        b = random.randint(0, a)
        answer = a - b
    elif operator == '*':
        a = random.randint(1, 10)
        b = random.randint(1, 10)
        answer = a * b
    else:  # division
        b = random.randint(1, 9)
        answer = random.randint(1, 10)
        a = answer * b
    
    if answer > 100:
        return generate_math_problem()
    
    display_op = '/' if operator == '/' else operator
    return {'question': f'{a} {display_op} {b}', 'answer': str(answer)}


def generate_options(correct_answer):
    """Generate 4 options including the correct answer"""
    options = [correct_answer]
    while len(options) < 4:
        wrong = correct_answer + random.randint(-10, 10)
        if wrong != correct_answer and wrong not in options and wrong > 0:
            options.append(wrong)
    random.shuffle(options)
    return options


# Fraud detection
async def is_fraud(session, user_id):
    """Check if user is in fraud database"""
    try:
        async with session.get(FRAUD_DB_URL) as resp:
            text = await resp.text()
            fraud_list = [line.strip() for line in text.split('\n') if line.strip()]
            return str(user_id) in fraud_list
    except:
        return False


# Message handlers
async def handle_message(session, message):
    chat_id = str(message.get('chat', {}).get('id', ''))
    text = message.get('text', '')
    
    # /start command
    if text == '/start':
        return await send_message(
            session, chat_id,
            'Hello! This is my chat bot. Please pass verification to chat with me. '
            'Your messages will be forwarded to me.\n\nBot Created Via @Squarelan'
        )
    
    # Admin commands
    if chat_id == ADMIN_UID:
        reply_to = message.get('reply_to_message')
        if not reply_to:
            return await send_message(
                session, ADMIN_UID,
                'Usage: Reply to a forwarded message and send your reply, '
                'or use `/block`, `/unblock`, `/checkblock` commands'
            )
        
        if text == '/block':
            return await handle_block(session, message)
        if text == '/unblock':
            return await handle_unblock(session, message)
        if text == '/checkblock':
            return await check_block(session, message)
        
        # Reply to user
        guest_chat_id = db.get(f'msg-map-{reply_to.get("message_id")}')
        if guest_chat_id:
            return await copy_message(session, guest_chat_id, chat_id, message.get('message_id'))
        return await send_message(session, ADMIN_UID, 'Cannot find corresponding user')
    
    # Regular user
    return await handle_guest_message(session, message)


async def handle_guest_message(session, message):
    chat_id = str(message.get('chat', {}).get('id', ''))
    
    # Check if blocked
    if db.get(f'isblocked-{chat_id}'):
        return await send_message(session, chat_id, 'You are blocked')
    
    # Check verification status
    verified = db.get(f'verified-{chat_id}')
    if not verified:
        expected = db.get(f'verify-{chat_id}')
        
        if not expected:
            # Generate verification problem
            problem = generate_math_problem()
            db.put(f'verify-{chat_id}', problem['answer'])
            
            options = generate_options(int(problem['answer']))
            keyboard = {
                'inline_keyboard': [
                    [
                        {'text': str(options[0]), 'callback_data': f'verify_{options[0]}_{problem["answer"]}'},
                        {'text': str(options[1]), 'callback_data': f'verify_{options[1]}_{problem["answer"]}'}
                    ],
                    [
                        {'text': str(options[2]), 'callback_data': f'verify_{options[2]}_{problem["answer"]}'},
                        {'text': str(options[3]), 'callback_data': f'verify_{options[3]}_{problem["answer"]}'}
                    ]
                ]
            }
            
            return await send_message(
                session, chat_id,
                f'Please answer the following question to verify you are not a bot:\n\n{problem["question"]} = ?',
                reply_markup=keyboard
            )
        else:
            return await send_message(session, chat_id, 'Please click the button above to select your answer')
    
    # Fraud check
    if await is_fraud(session, chat_id):
        return await send_message(session, ADMIN_UID, f'Warning: Fraud detected\nUID: {chat_id}')
    
    # Forward message to admin
    forward_result = await forward_message(
        session, ADMIN_UID,
        message.get('chat', {}).get('id'),
        message.get('message_id')
    )
    
    if forward_result.get('ok'):
        db.put(
            f'msg-map-{forward_result["result"]["message_id"]}',
            chat_id,
            ttl=2592000  # 30 days
        )
        
        # Notification feature
        if ENABLE_NOTIFICATION:
            last_msg_time = db.get(f'lastmsg-{chat_id}')
            if not last_msg_time or time.time() - last_msg_time > NOTIFY_INTERVAL:
                db.put(f'lastmsg-{chat_id}', time.time())
                try:
                    async with session.get(NOTIFICATION_URL) as resp:
                        notification = await resp.text()
                        await send_message(session, ADMIN_UID, notification)
                except:
                    pass


async def handle_callback_query(session, callback_query):
    user_id = str(callback_query.get('from', {}).get('id', ''))
    data = callback_query.get('data', '')
    message_id = callback_query.get('message', {}).get('message_id')
    callback_query_id = callback_query.get('id')
    
    if not data.startswith('verify_'):
        return
    
    parts = data.split('_')
    if len(parts) != 3:
        return
    
    _, user_answer, correct_answer = parts
    
    if user_answer == correct_answer:
        db.put(f'verified-{user_id}', True, ttl=259200)  # 3 days
        db.delete(f'verify-{user_id}')
        
        await edit_message_text(
            session, user_id, message_id,
            'Verification successful! You can now use the bot.'
        )
    else:
        await answer_callback_query(
            session, callback_query_id,
            'Wrong answer, please try again',
            show_alert=True
        )


async def handle_block(session, message):
    reply_to = message.get('reply_to_message')
    guest_chat_id = db.get(f'msg-map-{reply_to.get("message_id")}')
    
    if not guest_chat_id:
        return await send_message(session, ADMIN_UID, 'Cannot find corresponding user')
    
    if guest_chat_id == ADMIN_UID:
        return await send_message(session, ADMIN_UID, 'Cannot block yourself')
    
    db.put(f'isblocked-{guest_chat_id}', True)
    return await send_message(session, ADMIN_UID, f'UID:{guest_chat_id} blocked successfully')


async def handle_unblock(session, message):
    reply_to = message.get('reply_to_message')
    guest_chat_id = db.get(f'msg-map-{reply_to.get("message_id")}')
    
    if not guest_chat_id:
        return await send_message(session, ADMIN_UID, 'Cannot find corresponding user')
    
    db.put(f'isblocked-{guest_chat_id}', False)
    return await send_message(session, ADMIN_UID, f'UID:{guest_chat_id} unblocked successfully')


async def check_block(session, message):
    reply_to = message.get('reply_to_message')
    guest_chat_id = db.get(f'msg-map-{reply_to.get("message_id")}')
    
    if not guest_chat_id:
        return await send_message(session, ADMIN_UID, 'Cannot find corresponding user')
    
    blocked = db.get(f'isblocked-{guest_chat_id}')
    status = 'is blocked' if blocked else 'is not blocked'
    return await send_message(session, ADMIN_UID, f'UID:{guest_chat_id} {status}')


# HTTP handlers
async def webhook_handler(request):
    # Verify secret
    secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if secret != WEBHOOK_SECRET:
        return web.Response(status=403, text='Unauthorized')
    
    try:
        update = await request.json()
        logger.info(f'Received update: {json.dumps(update, ensure_ascii=False)[:200]}')
        
        async with ClientSession() as session:
            if 'message' in update:
                await handle_message(session, update['message'])
            if 'callback_query' in update:
                await handle_callback_query(session, update['callback_query'])
        
        return web.Response(text='Ok')
    except Exception as e:
        logger.error(f'Error handling update: {e}')
        return web.Response(status=500, text=str(e))


async def register_webhook(request):
    if not DOMAIN:
        return web.Response(text='DOMAIN not set')
    
    webhook_url = f'{DOMAIN}/webhook'
    async with ClientSession() as session:
        result = await api_request(session, 'setWebhook', {
            'url': webhook_url,
            'secret_token': WEBHOOK_SECRET
        })
    return web.Response(text=json.dumps(result, indent=2))


async def unregister_webhook(request):
    async with ClientSession() as session:
        result = await api_request(session, 'setWebhook', {'url': ''})
    return web.Response(text=json.dumps(result, indent=2))


async def health_check(request):
    return web.Response(text='Bot is running')


def create_app():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_post('/webhook', webhook_handler)
    app.router.add_get('/registerWebhook', register_webhook)
    app.router.add_get('/unRegisterWebhook', unregister_webhook)
    return app


if __name__ == '__main__':
    if not BOT_TOKEN:
        print('Error: BOT_TOKEN not set')
        print('Usage: BOT_TOKEN=xxx ADMIN_UID=xxx python3 tg_verify_bot.py')
        exit(1)
    if not ADMIN_UID:
        print('Error: ADMIN_UID not set')
        exit(1)
    
    print(f'''
+--------------------------------------------------------------+
|           Telegram Verification Bot - VPS Version            |
+--------------------------------------------------------------+
|  Port: {PORT:<54}|
|  Admin: {ADMIN_UID:<53}|
|  Database: {DB_PATH:<50}|
+--------------------------------------------------------------+
|  Endpoints:                                                  |
|    GET  /                    - Health check                  |
|    POST /webhook             - Telegram Webhook              |
|    GET  /registerWebhook     - Register Webhook              |
|    GET  /unRegisterWebhook   - Unregister Webhook            |
+--------------------------------------------------------------+
''')
    
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=PORT)
