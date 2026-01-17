#!/usr/bin/env node
/**
 * Telegram Verification Bot - VPS Version (Node.js)
 *
 * Features:
 * - Math verification for new users
 * - Message forwarding to admin
 * - Admin reply/block users
 * - Fraud detection
 */

const http = require('http');
const https = require('https');
const { URL } = require('url');
const path = require('path');
const fs = require('fs');

// Configuration
const BOT_TOKEN = process.env.BOT_TOKEN || '8324596212:ACHznhDgRuW2OcTYKAvFoa0UrDiMnef4Qyh';
const ADMIN_UID = process.env.ADMIN_UID || '1130431721';
const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET || 'W2OcTYKAvFoa0Ur';
const PORT = parseInt(process.env.PORT || '25591');
const DOMAIN = process.env.DOMAIN || '';
const DB_PATH = process.env.DB_PATH || 'bot_data.json';

const NOTIFY_INTERVAL = 24 * 3600 * 1000; // 1 day (ms)
const FRAUD_DB_URL = 'https://raw.githubusercontent.com/Squarelan/telegram-verify-bot/main/data/fraud.db';
const NOTIFICATION_URL = 'https://raw.githubusercontent.com/Squarelan/telegram-verify-bot/main/data/notification.txt';
const ENABLE_NOTIFICATION = false;

// Simple JSON database with TTL support
class Database {
  constructor(dbPath) {
    this.dbPath = dbPath;
    this.data = {};
    this._load();
  }

  _load() {
    try {
      if (fs.existsSync(this.dbPath)) {
        this.data = JSON.parse(fs.readFileSync(this.dbPath, 'utf8'));
      }
    } catch (e) {
      this.data = {};
    }
  }

  _save() {
    fs.writeFileSync(this.dbPath, JSON.stringify(this.data, null, 2));
  }

  get(key) {
    const item = this.data[key];
    if (!item) return null;
    if (item.expiresAt && Date.now() > item.expiresAt) {
      this.delete(key);
      return null;
    }
    return item.value;
  }

  put(key, value, ttl = null) {
    this.data[key] = {
      value,
      expiresAt: ttl ? Date.now() + ttl * 1000 : null
    };
    this._save();
  }

  delete(key) {
    delete this.data[key];
    this._save();
  }
}

const db = new Database(DB_PATH);

// HTTP request helper
function request(url, options = {}) {
  return new Promise((resolve, reject) => {
    const parsedUrl = new URL(url);
    const client = parsedUrl.protocol === 'https:' ? https : http;
    
    const req = client.request(url, {
      method: options.method || 'GET',
      headers: options.headers || {}
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve(data);
        }
      });
    });
    
    req.on('error', reject);
    if (options.body) req.write(options.body);
    req.end();
  });
}

// Telegram API functions
async function apiRequest(method, data = null) {
  const url = `https://api.telegram.org/bot${BOT_TOKEN}/${method}`;
  try {
    const result = await request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: data ? JSON.stringify(data) : null
    });
    if (!result.ok) {
      console.error('API error:', result);
    }
    return result;
  } catch (e) {
    console.error('API request failed:', e);
    return { ok: false, error: e.message };
  }
}

function sendMessage(chatId, text, replyMarkup = null) {
  const data = { chat_id: chatId, text };
  if (replyMarkup) data.reply_markup = replyMarkup;
  return apiRequest('sendMessage', data);
}

function copyMessage(chatId, fromChatId, messageId) {
  return apiRequest('copyMessage', {
    chat_id: chatId,
    from_chat_id: fromChatId,
    message_id: messageId
  });
}

function forwardMessage(chatId, fromChatId, messageId) {
  return apiRequest('forwardMessage', {
    chat_id: chatId,
    from_chat_id: fromChatId,
    message_id: messageId
  });
}

function editMessageText(chatId, messageId, text) {
  return apiRequest('editMessageText', {
    chat_id: chatId,
    message_id: messageId,
    text
  });
}

function answerCallbackQuery(callbackQueryId, text, showAlert = false) {
  return apiRequest('answerCallbackQuery', {
    callback_query_id: callbackQueryId,
    text,
    show_alert: showAlert
  });
}

// Math verification
function generateMathProblem() {
  const operators = ['+', '-', '*', '/'];
  const operator = operators[Math.floor(Math.random() * operators.length)];
  
  let a, b, answer;
  
  if (operator === '+') {
    a = Math.floor(Math.random() * 50) + 1;
    b = Math.floor(Math.random() * 50) + 1;
    answer = a + b;
  } else if (operator === '-') {
    a = Math.floor(Math.random() * 100) + 1;
    b = Math.floor(Math.random() * a);
    answer = a - b;
  } else if (operator === '*') {
    a = Math.floor(Math.random() * 10) + 1;
    b = Math.floor(Math.random() * 10) + 1;
    answer = a * b;
  } else {
    b = Math.floor(Math.random() * 9) + 1;
    answer = Math.floor(Math.random() * 10) + 1;
    a = answer * b;
  }
  
  if (answer > 100) {
    return generateMathProblem();
  }
  
  return { question: `${a} ${operator} ${b}`, answer: String(answer) };
}

function generateOptions(correctAnswer) {
  const options = [correctAnswer];
  while (options.length < 4) {
    const wrong = correctAnswer + Math.floor(Math.random() * 21) - 10;
    if (wrong !== correctAnswer && !options.includes(wrong) && wrong > 0) {
      options.push(wrong);
    }
  }
  return options.sort(() => Math.random() - 0.5);
}

// Fraud detection
async function isFraud(userId) {
  try {
    const text = await request(FRAUD_DB_URL);
    const fraudList = text.split('\n').map(s => s.trim()).filter(Boolean);
    return fraudList.includes(String(userId));
  } catch {
    return false;
  }
}

// Message handlers
async function handleMessage(message) {
  const chatId = String(message?.chat?.id || '');
  const text = message?.text || '';
  
  // /start command
  if (text === '/start') {
    return sendMessage(
      chatId,
      'Hello! This is my chat bot. Please pass verification to chat with me. ' +
      'Your messages will be forwarded to me.\n\nBot Created Via @Squarelan'
    );
  }
  
  // Admin commands
  if (chatId === ADMIN_UID) {
    const replyTo = message?.reply_to_message;
    if (!replyTo) {
      return sendMessage(
        ADMIN_UID,
        'Usage: Reply to a forwarded message and send your reply, ' +
        'or use `/block`, `/unblock`, `/checkblock` commands'
      );
    }
    
    if (text === '/block') return handleBlock(message);
    if (text === '/unblock') return handleUnblock(message);
    if (text === '/checkblock') return checkBlock(message);
    
    // Reply to user
    const guestChatId = db.get(`msg-map-${replyTo.message_id}`);
    if (guestChatId) {
      return copyMessage(guestChatId, chatId, message.message_id);
    }
    return sendMessage(ADMIN_UID, 'Cannot find corresponding user');
  }
  
  // Regular user
  return handleGuestMessage(message);
}

async function handleGuestMessage(message) {
  const chatId = String(message?.chat?.id || '');
  
  // Check if blocked
  if (db.get(`isblocked-${chatId}`)) {
    return sendMessage(chatId, 'You are blocked');
  }
  
  // Check verification status
  const verified = db.get(`verified-${chatId}`);
  if (!verified) {
    const expected = db.get(`verify-${chatId}`);
    
    if (!expected) {
      // Generate verification problem
      const problem = generateMathProblem();
      db.put(`verify-${chatId}`, problem.answer);
      
      const options = generateOptions(parseInt(problem.answer));
      const keyboard = {
        inline_keyboard: [
          [
            { text: String(options[0]), callback_data: `verify_${options[0]}_${problem.answer}` },
            { text: String(options[1]), callback_data: `verify_${options[1]}_${problem.answer}` }
          ],
          [
            { text: String(options[2]), callback_data: `verify_${options[2]}_${problem.answer}` },
            { text: String(options[3]), callback_data: `verify_${options[3]}_${problem.answer}` }
          ]
        ]
      };
      
      return sendMessage(
        chatId,
        `Please answer the following question to verify you are not a bot:\n\n${problem.question} = ?`,
        keyboard
      );
    } else {
      return sendMessage(chatId, 'Please click the button above to select your answer');
    }
  }
  
  // Fraud check
  if (await isFraud(chatId)) {
    return sendMessage(ADMIN_UID, `Warning: Fraud detected\nUID: ${chatId}`);
  }
  
  // Forward message to admin
  const forwardResult = await forwardMessage(
    ADMIN_UID,
    message.chat.id,
    message.message_id
  );
  
  if (forwardResult.ok) {
    db.put(
      `msg-map-${forwardResult.result.message_id}`,
      chatId,
      2592000 // 30 days
    );
    
    // Notification feature
    if (ENABLE_NOTIFICATION) {
      const lastMsgTime = db.get(`lastmsg-${chatId}`);
      if (!lastMsgTime || Date.now() - lastMsgTime > NOTIFY_INTERVAL) {
        db.put(`lastmsg-${chatId}`, Date.now());
        try {
          const notification = await request(NOTIFICATION_URL);
          await sendMessage(ADMIN_UID, notification);
        } catch {}
      }
    }
  }
}

async function handleCallbackQuery(callbackQuery) {
  const userId = String(callbackQuery?.from?.id || '');
  const data = callbackQuery?.data || '';
  const messageId = callbackQuery?.message?.message_id;
  const callbackQueryId = callbackQuery?.id;
  
  if (!data.startsWith('verify_')) return;
  
  const parts = data.split('_');
  if (parts.length !== 3) return;
  
  const [, userAnswer, correctAnswer] = parts;
  
  if (userAnswer === correctAnswer) {
    db.put(`verified-${userId}`, true, 259200); // 3 days
    db.delete(`verify-${userId}`);
    
    await editMessageText(
      userId, messageId,
      'Verification successful! You can now use the bot.'
    );
  } else {
    await answerCallbackQuery(
      callbackQueryId,
      'Wrong answer, please try again',
      true
    );
  }
}

async function handleBlock(message) {
  const replyTo = message.reply_to_message;
  const guestChatId = db.get(`msg-map-${replyTo.message_id}`);
  
  if (!guestChatId) {
    return sendMessage(ADMIN_UID, 'Cannot find corresponding user');
  }
  
  if (guestChatId === ADMIN_UID) {
    return sendMessage(ADMIN_UID, 'Cannot block yourself');
  }
  
  db.put(`isblocked-${guestChatId}`, true);
  return sendMessage(ADMIN_UID, `UID:${guestChatId} blocked successfully`);
}

async function handleUnblock(message) {
  const replyTo = message.reply_to_message;
  const guestChatId = db.get(`msg-map-${replyTo.message_id}`);
  
  if (!guestChatId) {
    return sendMessage(ADMIN_UID, 'Cannot find corresponding user');
  }
  
  db.put(`isblocked-${guestChatId}`, false);
  return sendMessage(ADMIN_UID, `UID:${guestChatId} unblocked successfully`);
}

async function checkBlock(message) {
  const replyTo = message.reply_to_message;
  const guestChatId = db.get(`msg-map-${replyTo.message_id}`);
  
  if (!guestChatId) {
    return sendMessage(ADMIN_UID, 'Cannot find corresponding user');
  }
  
  const blocked = db.get(`isblocked-${guestChatId}`);
  const status = blocked ? 'is blocked' : 'is not blocked';
  return sendMessage(ADMIN_UID, `UID:${guestChatId} ${status}`);
}

// HTTP server
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      try {
        resolve(JSON.parse(body));
      } catch {
        resolve(body);
      }
    });
    req.on('error', reject);
  });
}

async function handleRequest(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  
  // Health check
  if (url.pathname === '/' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('Bot is running');
    return;
  }
  
  // Webhook
  if (url.pathname === '/webhook' && req.method === 'POST') {
    const secret = req.headers['x-telegram-bot-api-secret-token'] || '';
    if (secret !== WEBHOOK_SECRET) {
      res.writeHead(403, { 'Content-Type': 'text/plain' });
      res.end('Unauthorized');
      return;
    }
    
    try {
      const update = await parseBody(req);
      console.log('Received update:', JSON.stringify(update).slice(0, 200));
      
      if (update.message) {
        await handleMessage(update.message);
      }
      if (update.callback_query) {
        await handleCallbackQuery(update.callback_query);
      }
      
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('Ok');
    } catch (e) {
      console.error('Error handling update:', e);
      res.writeHead(500, { 'Content-Type': 'text/plain' });
      res.end(e.message);
    }
    return;
  }
  
  // Register webhook
  if (url.pathname === '/registerWebhook' && req.method === 'GET') {
    if (!DOMAIN) {
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('DOMAIN not set');
      return;
    }
    
    const webhookUrl = `${DOMAIN}/webhook`;
    const result = await apiRequest('setWebhook', {
      url: webhookUrl,
      secret_token: WEBHOOK_SECRET
    });
    
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(result, null, 2));
    return;
  }
  
  // Unregister webhook
  if (url.pathname === '/unRegisterWebhook' && req.method === 'GET') {
    const result = await apiRequest('setWebhook', { url: '' });
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(result, null, 2));
    return;
  }
  
  // 404
  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('Not Found');
}

// Main
if (!BOT_TOKEN) {
  console.error('Error: BOT_TOKEN not set');
  console.error('Usage: BOT_TOKEN=xxx ADMIN_UID=xxx node index.js');
  process.exit(1);
}

if (!ADMIN_UID) {
  console.error('Error: ADMIN_UID not set');
  process.exit(1);
}

console.log(`
+--------------------------------------------------------------+
|           Telegram Verification Bot - VPS Version            |
|                        (Node.js)                             |
+--------------------------------------------------------------+
|  Port: ${PORT}                                               |
|  Admin: ${ADMIN_UID.padEnd(53)}|
|  Database: ${DB_PATH.padEnd(50)}|
+--------------------------------------------------------------+
|  Endpoints:                                                  |
|    GET  /                    - Health check                  |
|    POST /webhook             - Telegram Webhook              |
|    GET  /registerWebhook     - Register Webhook              |
|    GET  /unRegisterWebhook   - Unregister Webhook            |
+--------------------------------------------------------------+
`);

const server = http.createServer(handleRequest);
server.listen(PORT, '0.0.0.0', () => {
  console.log(`Server running on port ${PORT}`);
});
