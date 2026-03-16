import telebot, requests, os, time, urllib.parse, base64
from telebot import types
from flask import Flask
from threading import Thread

# --- SERVIDOR ---
app = Flask('')
@app.route('/')
def home(): return "MestreFisio V6.1 - Multimodal Ativo"

def run(): app.run(host='0.0.0.0', port=10000)

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True)

# --- FUNÇÃO DE GERAÇÃO DE IMAGEM ---
def enviar_ilustracao(chat_id, termo, tipo="anatomia"):
    estilo = "medical atlas anatomy illustration, high detail, white background" if tipo == "anatomia" else "physiotherapy exercise execution, professional photo"
    prompt_url = urllib.parse.quote(f"{termo}, {estilo}")
    seed = int(time.time())
    url_imagem = f"https://pollinations.ai/p/{prompt_url}?width=1024&height=1024&seed={seed}&model=flux&nologo=true"
    
    try:
        prefixo = "🦴 ANATOMIA" if tipo == "anatomia" else "🏃 EXECUÇÃO/TESTE"
        bot.send_photo(chat_id, url_imagem, caption=f"**{prefixo}:** {termo.upper()}")
    except:
        pass

# --- PROCESSADOR DE RESPOSTA ---
def processar_resposta_ia(message, analise):
    # Limpa o texto dos comandos de imagem
    texto_final = analise.split("ANATOMIA:")[0].split("EXECUCAO:")[0].strip()
    
    if len(texto_final) > 4000:
        for i in range(0, len(texto_final), 4000): bot.send_message(message.chat.id, texto_final[i:i+4000])
    else:
        bot.send_message(message.chat.id, texto_final)

    # Busca termos para as duas imagens
    if "ANATOMIA:" in analise:
        termo_ana = analise.split("ANATOMIA:")[1].split("EXECUCAO:")[0].strip().replace("[","").replace("]","")
        enviar_ilustracao(message.chat.id, termo_ana, "anatomia")
    
    if "EXECUCAO:" in analise:
        termo_exe = analise.split("EXECUCAO:")[1].strip().replace("[","").replace("]","")
        enviar_ilustracao(message.chat.id, termo_exe, "execucao")
    
    bot.send_message(message.chat.id, "O que deseja fazer agora?", reply_markup=menu_principal())

# --- HANDLER DE FOTOS ---
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    aguarde = bot.send_message(message.chat.id, "🔍 Analisando imagem/laudo...")
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    img_b64 = base64.b64encode(downloaded_file).decode('utf-8')
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    payload = {
        "contents": [{
            "parts": [
                {"text": "Atue como Fisioterapeuta PhD. Analise a imagem/laudo. No final indique ANATOMIA: [termo] e EXECUCAO: [termo]"},
                {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
            ]
        }]
    }
    try:
        res = requests.post(url, json=payload).json()
        bot.delete_message(message.chat.id, aguarde.message_id)
        processar_resposta_ia(message, res['candidates'][0]['content']['parts'][0]['text'])
    except:
        bot.send_message(message.chat.id, "❌ Erro na análise visual.")

# --- HANDLER DE TEXTO ---
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    if message.text.startswith('/'): return
    aguarde = bot.send_message(message.chat.id, "🧠 Analisando...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    prompt = f"Fisioterapeuta PhD: {message.text}. No final indique ANATOMIA: [termo] e EXECUCAO: [termo]"
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}).json()
        bot.delete_message(message.chat.id, aguarde.message_id)
        processar_resposta_ia(message, res['candidates'][0]['content']['parts'][0]['text'])
    except:
        bot.send_message(message.chat.id, "❌ Erro.")

def menu_principal():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👤 Novo Paciente", callback_data="novo"),
               types.InlineKeyboardButton("📚 Dúvida", callback_data="duvida"))
    return markup

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling()
