import telebot
import sqlite3
import requests
import os

# --- CONFIGURAÇÕES CRÍTICAS ---
# Substitui pelos teus dados reais entre as aspas
TOKEN_TELEGRAM = "8736702883:AAFHITONmtv6q3ANO_3d4J160RdBor-6CL0"
API_KEY_IA = "AIzaSyAekuq7TLNhP1RlpAKfvvwfl-V5dPtt5dw"
MODELO = "gemma-3-27b-it"

bot = telebot.TeleBot(TOKEN_TELEGRAM)

# --- BANCO DE DADOS (SQLite) ---
def init_db():
    # O check_same_thread=False é vital para rodar em servidores
    conn = sqlite3.connect('fisio_clinica.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS prontuarios 
                      (id INTEGER PRIMARY KEY, paciente TEXT, analise TEXT, data DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn

db_conn = init_db()

# --- LÓGICA DO BOT ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "🚀 *AGENTE FISIO 2026 ATIVO!*\n\n"
        "Olá, colega. Para começar:\n"
        "1️⃣ Digite o *NOME COMPLETO* do paciente.\n"
        "2️⃣ Eu buscarei o histórico ou iniciarei uma nova ficha."
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    nome_paciente = message.text.upper().strip()
    
    # Busca histórico no banco de dados
    cursor = db_conn.cursor()
    cursor.execute("SELECT analise, data FROM prontuarios WHERE paciente=? ORDER BY id DESC LIMIT 1", (nome_paciente,))
    hist = cursor.fetchone()
    
    contexto = ""
    if hist:
        contexto = f"\n[HISTÓRICO PRÉVIO ({hist[1]})]: {hist[0][:600]}..."
        bot.send_message(message.chat.id, f"📖 *Histórico de {nome_paciente} localizado!* Vou considerá-lo na análise.", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, f"🆕 *Novo paciente:* {nome_paciente}. Criando ficha inicial.")

    msg = bot.send_message(message.chat.id, "✍️ Agora, descreva o *Quadro Clínico atual* ou a evolução deste paciente:")
    # "Prende" o utilizador para a próxima resposta ser enviada para a IA
    bot.register_next_step_handler(msg, processar_ia, nome_paciente, contexto)

def processar_ia(message, nome, contexto):
    queixa_atual = message.text
    bot.send_message(message.chat.id, "🧠 *Gemma 3 27B processando...*\nIsso pode levar até 30 segundos devido à complexidade da análise.", parse_mode="Markdown")

    # Prompt Mestre para garantir profundidade
    instrucao_mestre = (
        "Atue como um Fisioterapeuta Doutor e Especialista. "
        "Forneça uma análise clínica extremamente técnica e profunda em 12 tópicos. "
        "Use termos como biomecânica, neurodinâmica e fisiopatologia. "
        f"{contexto}\n\n"
        "Se houver histórico, compare a evolução. Se não, foque no diagnóstico diferencial."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    payload = {
        "contents": [{
            "parts": [{"text": f"{instrucao_mestre}\n\nPaciente: {nome}\nQuadro Clínico Atual: {queixa_atual}"}]
        }]
    }

    try:
        response = requests.post(url, json=payload, timeout=120)
        dados = response.json()
        analise_final = dados['candidates'][0]['content']['parts'][0]['text']
        
        # Salva a nova análise no banco de dados
        cursor = db_conn.cursor()
        cursor.execute("INSERT INTO prontuarios (paciente, analise) VALUES (?, ?)", (nome, analise_final))
        db_conn.commit()

        # Envio em blocos (O Telegram tem limite de 4096 caracteres por mensagem)
        if len(analise_final) > 4000:
            for i in range(0, len(analise_final), 4000):
                bot.send_message(message.chat.id, analise_final[i:i+4000])
        else:
            bot.send_message(message.chat.id, analise_final)
            
        bot.send_message(message.chat.id, "✅ *Prontuário salvo com sucesso!*", parse_mode="Markdown")
            
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ *Erro de Conexão:* {str(e)}")

# Mantém o bot rodando infinitamente
print("🤖 Bot Fisio Online 24h...")
bot.infinity_polling()
