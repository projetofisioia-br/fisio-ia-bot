import telebot, requests, os, time, urllib.parse, base64
from telebot import types
from flask import Flask
from threading import Thread

# --- SERVIDOR MÍNIMO PARA MANTER ONLINE ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V6.2 - Estabilizado"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True)

def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo"),
               types.InlineKeyboardButton("📚 Dúvida Técnica", callback_data="duvida"))
    return markup

# --- FUNÇÃO DE IMAGEM COM TIMEOUT ---
def enviar_ilustracao(chat_id, termo, tipo="anatomia"):
    estilo = "medical anatomy atlas" if tipo == "anatomia" else "physiotherapy exercise"
    prompt_url = urllib.parse.quote(f"{termo} {estilo}")
    url_imagem = f"https://pollinations.ai/p/{prompt_url}?width=1024&height=1024&nologo=true&seed={int(time.time())}"
    try:
        prefixo = "🦴 ANATOMIA" if tipo == "anatomia" else "🏃 EXECUÇÃO"
        bot.send_photo(chat_id, url_imagem, caption=f"**{prefixo}:** {termo.upper()}", timeout=10)
    except: pass

# --- MOTOR DE RESPOSTA ---
def responder(message, texto_usuario, imagem_b64=None):
    aguarde = bot.send_message(message.chat.id, "🧠 Analisando...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    # Prompt mestre para garantir as tags de imagem
    instrucao = "Atue como Fisioterapeuta PhD. Responda em português. No final da resposta, indique estritamente: ANATOMIA: [termo em inglês] e EXECUCAO: [termo em inglês]."
    
    if imagem_b64:
        payload = {"contents": [{"parts": [{"text": f"{instrucao} Analise esta imagem: {texto_usuario}"}, {"inline_data": {"mime_type": "image/jpeg", "data": imagem_b64}}]}]}
    else:
        payload = {"contents": [{"parts": [{"text": f"{instrucao} Pergunta: {texto_usuario}"}]}]}

    try:
        res = requests.post(url, json=payload, timeout=30).json()
        analise = res['candidates'][0]['content']['parts'][0]['text']
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        # Limpar texto e extrair termos de imagem
        texto_final = analise.split("ANATOMIA:")[0].split("EXECUCAO:")[0].strip()
        bot.send_message(message.chat.id, texto_final, parse_mode="Markdown")

        if "ANATOMIA:" in analise:
            termo = analise.split("ANATOMIA:")[1].split("EXECUCAO:")[0].strip().replace("[","").replace("]","")
            enviar_ilustracao(message.chat.id, termo, "anatomia")
        if "EXECUCAO:" in analise:
            termo = analise.split("EXECUCAO:")[1].strip().replace("[","").replace("]","")
            enviar_ilustracao(message.chat.id, termo, "execucao")

    except Exception as e:
        bot.send_message(message.chat.id, "❌ Erro na conexão com a IA. Tente novamente.")
        print(f"Erro: {e}")

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "🚀 **MestreFisio V6.2 Online!**\nEnvie texto ou foto de exame:", reply_markup=menu_principal(), parse_mode="Markdown")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    img_b64 = base64.b64encode(downloaded_file).decode('utf-8')
    responder(message, "Análise de imagem", img_b64)

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    if message.text.startswith('/'): return
    responder(message, message.text)

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "📝 Pode digitar sua dúvida ou enviar a foto do laudo:")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(timeout=20, long_polling_timeout=5)
