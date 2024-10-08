from os import environ as env
from quart import Quart, Blueprint, Response, request, redirect, render_template, jsonify

from uvicorn import Server as UvicornServer, Config
from logging import getLogger, basicConfig
from telethon import TelegramClient
from telethon.tl.custom import Message
from datetime import datetime
from mimetypes import guess_type
from math import ceil, floor

# Configurations
class Telegram:
    API_ID = int("12595500")
    API_HASH = "e3b216e300f297f782f5984b462979a7"
    CHANNEL_ID = -1001626866241
    BOT_USERNAME = "YourBotUsername"  # Set your bot username

class Server:
    BASE_URL = env.get("BASE_URL", "http://164.92.130.158:7000")
    BIND_ADDRESS = env.get("BIND_ADDRESS", "0.0.0.0")
    PORT = int(env.get("PORT", 7000))

# Logging Configuration
basicConfig(level='INFO')
logger = getLogger('bot')

# Initialize Telegram Client
TelegramBot = TelegramClient(
    session='bot',
    api_id=Telegram.API_ID,
    api_hash=Telegram.API_HASH
)

# Setup Quart Application
app = Quart(__name__)
app.config['RESPONSE_TIMEOUT'] = None

@app.before_serving
async def before_serve():
    await TelegramBot.start()
    logger.info('Web server is started!')
    logger.info(f'Server running on {Server.BIND_ADDRESS}:{Server.PORT}')

async def get_message(message_id: int) -> Message | None:
    message = None
    try:
        message = await TelegramBot.get_messages(Telegram.CHANNEL_ID, ids=message_id)
    except Exception as e:
        logger.error(f"An error occurred while fetching the message: {e}")
    
    return message

def get_file_properties(message: Message):
    file_name = message.file.name
    file_size = message.file.size or 0
    mime_type = message.file.mime_type

    if not file_name:
        attributes = {
            'video': 'mp4',
            'audio': 'mp3',
            'voice': 'ogg',
            'photo': 'jpg',
            'video_note': 'mp4'
        }

        for attribute in attributes:
            media = getattr(message, attribute, None)
            if media:
                file_type, file_format = attribute, attributes[attribute]
                break
        
        if not media:
            return None, None, None  # Handle the case where media is invalid

        date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f'{file_type}-{date}.{file_format}'
    
    if not mime_type:
        mime_type = guess_type(file_name)[0] or 'application/octet-stream'
    
    return file_name, file_size, mime_type

# Define Blueprint
bp = Blueprint('main', __name__)

@bp.route('/')
async def home():
    return redirect(f'https://t.me/{Telegram.BOT_USERNAME}')

@bp.route('/dl/<int:file_id>')
async def transmit_file(file_id):
    logger.info(file_id)
    file = await get_message(message_id=file_id) or abort(404)
    
    range_header = request.headers.get('Range', 0)

    file_name, file_size, mime_type = get_file_properties(file)
    
    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = 0
        until_bytes = file_size - 1

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        abort(416)

    chunk_size = 1024 * 512
    until_bytes = min(until_bytes, file_size - 1)

    headers = {
        "Content-Type": mime_type,
        "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
        "Content-Length": str(until_bytes - from_bytes + 1),
        "Content-Disposition": f'attachment; filename="{file_name}"',
        "Accept-Ranges": "bytes",
    }

    async def file_generator():
        async for chunk in TelegramBot.iter_download(file, offset=from_bytes, chunk_size=chunk_size):
            yield chunk

    return Response(file_generator(), headers=headers, status=206 if range_header else 200)

@bp.route('/stream/<int:file_id>')
async def stream_file(file_id):
    code = request.args.get('code') or abort(401)
    return await render_template('player.html', mediaLink=f'{Server.BASE_URL}/dl/{file_id}?code={code}')

# Error Handling

class HTTPError(Exception):
    status_code: int = None
    description: str = None

    def __init__(self, status_code, description):
        self.status_code = status_code
        self.description = description
        super().__init__(self.status_code, self.description)

error_messages = {
    400: 'Invalid request.',
    401: 'File code is required to download the file.',
    403: 'Invalid file code.',
    404: 'File not found.',
    500: 'Internal server error.'
}

async def invalid_request(_):
    return 'Invalid request.', 400

async def not_found(_):
    return 'Resource not found.', 404

async def http_error(error: HTTPError):
    error_message = error_messages.get(error.status_code)
    return error.description or error_message, error.status_code

def abort(status_code: int = 500, description: str = None):
    raise HTTPError(status_code, description)

@app.errorhandler(HTTPError)
async def handle_http_error(error: HTTPError):
    return await http_error(error)

@app.errorhandler(400)
async def handle_bad_request(_):
    return await invalid_request(_)

@app.errorhandler(401)
async def handle_unauthorized(_):
    return 'File code is required to download the file.', 401

@app.errorhandler(403)
async def handle_forbidden(_):
    return 'Invalid file code.', 403

@app.errorhandler(404)
async def handle_not_found(_):
    return 'Resource not found.', 404

@app.errorhandler(405)
async def handle_method_not_allowed(_):
    return 'Invalid request method.', 405

@app.errorhandler(500)
async def handle_internal_server_error(_):
    return 'Internal server error.', 500

# Register the blueprint
app.register_blueprint(bp)

# Run the server
if __name__ == '__main__':
    server = UvicornServer(
        Config(
            app=app,
            host=Server.BIND_ADDRESS,
            port=Server.PORT,
        )
    )
    server.run()
