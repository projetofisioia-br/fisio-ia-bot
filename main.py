import telebot
import sqlite3
import requests
from flask import Flask
from threading import Thread

# --- DISFARCE PARA O RENDER ---
app = Flask('')
@app.route('/')
def home(): return "Agente Fisio Online"
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
    bot.send_message(message.chat.id, "🧠 Analisando quadro clínico... Aguarde.")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    # Prompt mais direto para evitar bloqueios de segurança
    payload = {
        "contents": [{"parts": [{"text": f"Analise clínica fisioterapêutica para o paciente {nome}: {queixa}"}]}]
    }
    
    try:
        response = requests.post(url, json=payload)
        res_data = response.json()
        
        # Verificação robusta da resposta
        if 'candidates' in res_data and res_data['candidates'][0].get('content'):
            analise = res_data['candidates'][0]['content']['parts'][0]['text']
            
            # Salvar no banco
            cursor = db_conn.cursor()
            cursor.execute("INSERT INTO prontuarios (paciente, analise) VALUES (?, ?)", (nome, analise))
            db_conn.commit()
            
            # Enviar para o Telegram em partes se for grande
            if len(analise) > 4000:
                for i in range(0, len(analise), 4000):
                    bot.send_message(message.chat.id, analise[i:i+4000])
            else:
                bot.send_message(message.chat.id, analise)
        else:
            # Se a IA bloquear por segurança ou erro de chave
            erro_msg = res_data.get('error', {}).get('message', 'A IA bloqueou a resposta por segurança ou a chave é inválida.')
            bot.send_message(message.chat.id, f"⚠️ Erro na IA: {erro_msg}")
            
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Erro de conexão: {e}")

if __name__ == "__main__":
    keep_alive()
    print("Bot Rodando...")
    bot.infinity_polling()
