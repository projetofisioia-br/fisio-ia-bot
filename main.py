import telebot
import sqlite3
import requests
from flask import Flask
from threading import Thread

# --- DISFARCE PARA O RENDER ---
app = Flask('')
@app.route('/')
def home(): return "Bot Online"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run)
    t.start()

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8736702883:AAFHITONmtv6q3ANO_3d4J160RdBor-6CL0"
API_KEY_IA = "AIzaSyAekuq7TLNhP1RlpAKfvvwfl-V5dPtt5dw"
MODELO = "gemma-3-27b-it"

bot = telebot.TeleBot(TOKEN_TELEGRAM)

def init_db():
    conn = sqlite3.connect('fisio.db', check_same_thread=False)
    conn.cursor().execute('''CREATE TABLE IF NOT EXISTS prontuarios 
         (id INTEGER PRIMARY KEY, paciente TEXT, analise TEXT, data DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn

db_conn = init_db()

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🚀 AGENTE FISIO ATIVO!\nDigite o NOME DO PACIENTE.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    nome = message.text.upper().strip()
    bot.send_message(message.chat.id, f"👤 Paciente: {nome}\nDescreva o quadro clínico:")
    bot.register_next_step_handler(message, processar_ia, nome)

def processar_ia(message, nome):
    queixa = message.text
    bot.send_message(message.chat.id, "🧠 Analisando...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    prompt = f"Atue como Fisioterapeuta Especialista. Analise em 12 tópicos: {queixa}"
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}).json()
        analise = res['candidates'][0]['content']['parts'][0]['text']
        db_conn.cursor().execute("INSERT INTO prontuarios (paciente, analise) VALUES (?, ?)", (nome, analise))
        db_conn.commit()
        bot.send_message(message.chat.id, analise)
    except Exception as e:
        bot.send_message(message.chat.id, f"Erro: {e}")

if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling()
