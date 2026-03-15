import telebot, requests, os, time, urllib.parse
from telebot import types
from flask import Flask
from threading import Thread

app = Flask('')
@app.route('/')
def home(): return "MestreFisio V6 - Visão e Dupla Imagem Ativa"

def run(): app.run(host='0.0.0.0', port=10000)

def keep_alive():
    url_do_seu_bot = "https://fisio-ia-bot.onrender.com" 
    while True:
        try: requests.get(url_do_seu_bot)
        except: pass
        time.sleep(600)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True)

def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Analisar Novo Paciente", callback_data="novo_paciente")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    markup.add(btn_paciente, btn_duvida)
    return markup

# --- FUNÇÃO DE GERAÇÃO DE IMAGEM MELHORADA ---
def enviar_ilustracao(chat_id, termo, tipo="anatomia"):
    estilo = "medical atlas anatomy illustration, high detail, white background, no text" if tipo == "anatomia" else "physiotherapy clinical test execution, professional photography, no text"
    prompt_url = urllib.parse.quote(f"{termo}, {estilo}")
    
    # Seed aleatório para evitar cache de erro
    seed = int(time.time())
    url_imagem = f"https://pollinations.ai/p/{prompt_url}?width=1024&height=1024&seed={seed}&model=flux&nologo=true"
    
    try:
        legenda = f"🦴 **ANATOMIA:** {termo.upper()}" if tipo == "anatomia" else f"🏃 **EXECUÇÃO:** {termo.upper()}"
        bot.send_photo(chat_id, url_imagem, caption=legenda)
    except:
        print(f"Erro ao gerar imagem de {tipo}")

# --- TRATAMENTO DE VISÃO (LEITURA DE LAUDOS/FOTOS) ---
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    aguarde = bot.send_message(message.chat.id, "🔍 **Analisando imagem/laudo com visão computacional...**")
    
    # Pega a foto de maior resolução
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Prepara para o Gemini
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    headers = {'Content-Type': 'application/json'}
    
    import base64
    image_data = base64.b64encode(downloaded_file).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analise esta imagem clínica (laudo, exame ou teste). Extraia os dados relevantes e sugira conduta fisioterapêutica PhD. Ao final, indique: ANATOMIA: [termo] e EXECUCAO: [termo]"},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_data}}
            ]
        }]
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        analise = response.json()['candidates'][0]['content']['parts'][0]['text']
        bot.delete_message(message.chat.id, aguarde.message_id)
        processar_resposta_final(message, analise)
    except:
        bot.send_message(message.chat.id, "❌ Erro ao ler a imagem. Tente enviar um texto ou outra foto.")

# --- LÓGICA DE RESPOSTA ---
def processar_resposta_final(message, analise):
    # Separa os comandos de imagem
    texto_limpo = analise.split("ANATOMIA:")[0].split("EXECUCAO:")[0].strip()
    bot.send_message(message.chat.id, texto_limpo)

    # Envia as duas imagens se existirem
    if "ANATOMIA:" in analise:
        termo_ana = analise.split("ANATOMIA:")[1].split("EXECUCAO:")[0].strip().replace("[","").replace("]","")
        enviar_ilustracao(message.chat.id, termo_ana, "anatomia")
    
    if "EXECUCAO:" in analise:
        termo_exe = analise.split("EXECUCAO:")[1].strip().replace("[","").replace("]","")
        enviar_ilustracao(message.chat.id, termo_exe, "execucao")
    
    bot.send_message(message.chat.id, "O que deseja fazer agora?", reply_markup=menu_principal())

# (Manter funções de callback e start do código anterior...)
@bot.message_handler(commands=['start'])
def start(message): bot.send_message(message.chat.id, "🚀 **MestreFisio V6 Ativo!**\nEnvie um texto ou uma FOTO de exame/laudo:", reply_markup=menu_principal())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Nome do paciente:")
        bot.register_next_step_handler(msg, lambda m: bot.send_message(m.chat.id, "Descreva o caso ou envie a foto do laudo:"))
    elif call.data == "duvida_tecnica":
        bot.send_message(call.message.chat.id, "💡 Digite sua dúvida ou envie uma imagem:")

if __name__ == "__main__":
    Thread(target=run).start()
    Thread(target=keep_alive).start()
    bot.remove_webhook()
    bot.infinity_polling()
