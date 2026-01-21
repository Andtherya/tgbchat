#!/usr/bin/env python3
"""
Telegram Verification Bot 
No external dependencies - uses only Python standard library
"""

import os
import json
import random
import sqlite3
import time
import logging
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8324596212:ACHznhDgRuW2OcTYKAvFoa0UrDiMnef4Qyh')
ADMIN_UID = os.environ.get('ADMIN_UID', '1130431721')
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', 'W2OcTYKAvFoa0Ur')
PORT = int(os.environ.get('PORT', '8658'))
DOMAIN = os.environ.get('DOMAIN', '')
DB_PATH = os.environ.get('DB_PATH', 'bot_data.db')

NOTIFY_INTERVAL = 24 * 3600
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


# HTTP client functions
def http_get(url, timeout=10):
    """Simple HTTP GET request"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'TelegramBot/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8')
    except Exception as e:
        logger.error(f'HTTP GET failed: {e}')
        return None


def http_post_json(url, data, timeout=10):
    """Simple HTTP POST request with JSON body"""
    try:
        json_data = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=json_data,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'TelegramBot/1.0'
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode('utf-8')
            return json.loads(error_body)
        except:
            return {'ok': False, 'error': str(e)}
    except Exception as e:
        logger.error(f'HTTP POST failed: {e}')
        return {'ok': False, 'error': str(e)}


# Telegram API functions
def api_request(method, data=None):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/{method}'
    result = http_post_json(url, data or {})
    if not result.get('ok'):
        logger.error(f'API error: {result}')
    return result


def send_message(chat_id, text, reply_markup=None):
    data = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        data['reply_markup'] = reply_markup
    return api_request('sendMessage', data)


def copy_message(chat_id, from_chat_id, message_id):
    return api_request('copyMessage', {
        'chat_id': chat_id,
        'from_chat_id': from_chat_id,
        'message_id': message_id
    })


def forward_message(chat_id, from_chat_id, message_id):
    return api_request('forwardMessage', {
        'chat_id': chat_id,
        'from_chat_id': from_chat_id,
        'message_id': message_id
    })


def edit_message_text(chat_id, message_id, text):
    return api_request('editMessageText', {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text
    })


def answer_callback_query(callback_query_id, text, show_alert=False):
    return api_request('answerCallbackQuery', {
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
def is_fraud(user_id):
    """Check if user is in fraud database"""
    try:
        text = http_get(FRAUD_DB_URL)
        if text:
            fraud_list = [line.strip() for line in text.split('\n') if line.strip()]
            return str(user_id) in fraud_list
    except:
        pass
    return False


# Message handlers
def handle_message(message):
    chat_id = str(message.get('chat', {}).get('id', ''))
    text = message.get('text', '')
    
    # /start command
    if text == '/start':
        return send_message(
            chat_id,
            'Hello! This is my chat bot. Please pass verification to chat with me. '
            'Your messages will be forwarded to me.\n\nBot Created Via @Squarelan'
        )
    
    # Admin commands
    if chat_id == ADMIN_UID:
        reply_to = message.get('reply_to_message')
        if not reply_to:
            return send_message(
                ADMIN_UID,
                'Usage: Reply to a forwarded message and send your reply, '
                'or use `/block`, `/unblock`, `/checkblock` commands'
            )
        
        if text == '/block':
            return handle_block(message)
        if text == '/unblock':
            return handle_unblock(message)
        if text == '/checkblock':
            return check_block(message)
        
        # Reply to user
        guest_chat_id = db.get(f'msg-map-{reply_to.get("message_id")}')
        if guest_chat_id:
            return copy_message(guest_chat_id, chat_id, message.get('message_id'))
        return send_message(ADMIN_UID, 'Cannot find corresponding user')
    
    # Regular user
    return handle_guest_message(message)


def handle_guest_message(message):
    chat_id = str(message.get('chat', {}).get('id', ''))
    
    # Check if blocked
    if db.get(f'isblocked-{chat_id}'):
        return send_message(chat_id, 'You are blocked')
    
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
            
            return send_message(
                chat_id,
                f'Please answer the following question to verify you are not a bot:\n\n{problem["question"]} = ?',
                reply_markup=keyboard
            )
        else:
            return send_message(chat_id, 'Please click the button above to select your answer')
    
    # Fraud check
    if is_fraud(chat_id):
        return send_message(ADMIN_UID, f'Warning: Fraud detected\nUID: {chat_id}')
    
    # Forward message to admin
    forward_result = forward_message(
        ADMIN_UID,
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
                    notification = http_get(NOTIFICATION_URL)
                    if notification:
                        send_message(ADMIN_UID, notification)
                except:
                    pass


def handle_callback_query(callback_query):
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
        
        edit_message_text(
            user_id, message_id,
            'Verification successful! You can now use the bot.'
        )
    else:
        answer_callback_query(
            callback_query_id,
            'Wrong answer, please try again',
            show_alert=True
        )


def handle_block(message):
    reply_to = message.get('reply_to_message')
    guest_chat_id = db.get(f'msg-map-{reply_to.get("message_id")}')
    
    if not guest_chat_id:
        return send_message(ADMIN_UID, 'Cannot find corresponding user')
    
    if guest_chat_id == ADMIN_UID:
        return send_message(ADMIN_UID, 'Cannot block yourself')
    
    db.put(f'isblocked-{guest_chat_id}', True)
    return send_message(ADMIN_UID, f'UID:{guest_chat_id} blocked successfully')


def handle_unblock(message):
    reply_to = message.get('reply_to_message')
    guest_chat_id = db.get(f'msg-map-{reply_to.get("message_id")}')
    
    if not guest_chat_id:
        return send_message(ADMIN_UID, 'Cannot find corresponding user')
    
    db.put(f'isblocked-{guest_chat_id}', False)
    return send_message(ADMIN_UID, f'UID:{guest_chat_id} unblocked successfully')


def check_block(message):
    reply_to = message.get('reply_to_message')
    guest_chat_id = db.get(f'msg-map-{reply_to.get("message_id")}')
    
    if not guest_chat_id:
        return send_message(ADMIN_UID, 'Cannot find corresponding user')
    
    blocked = db.get(f'isblocked-{guest_chat_id}')
    status = 'is blocked' if blocked else 'is not blocked'
    return send_message(ADMIN_UID, f'UID:{guest_chat_id} {status}')


# HTTP Server
class BotHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(f'{self.address_string()} - {format % args}')
    
    def send_json(self, data, status=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
    
    def send_text(self, text, status=200):
        body = text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
    
    def do_GET(self):
        path = urlparse(self.path).path
        
        if path == '/':
            self.send_text('Bot is running')
        elif path == '/registerWebhook':
            self.handle_register_webhook()
        elif path == '/unRegisterWebhook':
            self.handle_unregister_webhook()
        else:
            self.send_text('Not Found', 404)
    
    def do_POST(self):
        path = urlparse(self.path).path
        
        if path == '/webhook':
            self.handle_webhook()
        else:
            self.send_text('Not Found', 404)
    
    def handle_webhook(self):
        # Verify secret
        secret = self.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if secret != WEBHOOK_SECRET:
            self.send_text('Unauthorized', 403)
            return
        
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            update = json.loads(body.decode('utf-8'))
            
            logger.info(f'Received update: {json.dumps(update, ensure_ascii=False)[:200]}')
            
            if 'message' in update:
                handle_message(update['message'])
            if 'callback_query' in update:
                handle_callback_query(update['callback_query'])
            
            self.send_text('Ok')
        except Exception as e:
            logger.error(f'Error handling update: {e}')
            self.send_text(str(e), 500)
    
    def handle_register_webhook(self):
        if not DOMAIN:
            self.send_text('DOMAIN not set')
            return
        
        webhook_url = f'{DOMAIN}/webhook'
        result = api_request('setWebhook', {
            'url': webhook_url,
            'secret_token': WEBHOOK_SECRET
        })
        self.send_text(json.dumps(result, indent=2))
    
    def handle_unregister_webhook(self):
        result = api_request('setWebhook', {'url': ''})
        self.send_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    if not BOT_TOKEN:
        print('Error: BOT_TOKEN not set')
        print('Usage: BOT_TOKEN=xxx ADMIN_UID=xxx python3 tg_bot_stdlib.py')
        exit(1)
    if not ADMIN_UID:
        print('Error: ADMIN_UID not set')
        exit(1)
    
    print(f'''
+--------------------------------------------------------------+
|    Telegram Verification Bot - Standard Library Version      |
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
|  No external dependencies required!                          |
+--------------------------------------------------------------+
''')
    
    server = HTTPServer(('0.0.0.0', PORT), BotHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down...')
        server.shutdown()
