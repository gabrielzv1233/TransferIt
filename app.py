from flask import Flask, request, jsonify, send_from_directory, render_template, url_for, redirect, session
from werkzeug.exceptions import RequestEntityTooLarge
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from datetime import timedelta
import secrets
import random
import shutil
import json
import uuid
import sys
import os

filesizeMB = 500

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
app.config['MAX_CONTENT_LENGTH'] = filesizeMB * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*")
script_path = os.path.dirname(os.path.abspath(sys.argv[0]))
CLIENTS_FOLDER = script_path + '/sessions/'
CLIENTFOLDERS_FILE = script_path + '/clientfolders.json'

if os.path.exists(CLIENTS_FOLDER):
    shutil.rmtree(CLIENTS_FOLDER)
os.makedirs(CLIENTS_FOLDER, exist_ok=True)

if not os.path.exists(CLIENTFOLDERS_FILE):
    with open(CLIENTFOLDERS_FILE, 'w') as f:
        json.dump({}, f)

@app.route('/')
def main_page():
    return render_template('index.html')

@app.route('/googlef2e8053b928e829b.html')
def gsearchv():
    return "google-site-verification: googlef2e8053b928e829b.html"

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    return jsonify({"error": f"File is too large. The maximum allowed size is {filesizeMB} MB."}), 413

def generate_short_uuid():
    short_uuid = str(uuid.uuid4())[:8]
    short_uuid = ''.join(random.sample(short_uuid, 6))
    randomized_uuid = ''.join(
        char.upper() if random.choice([True, False]) else char.lower() 
        for char in short_uuid
    )
    return randomized_uuid

@app.route('/generate_link', methods=['POST'])
def generate_link():
    link_uuid = generate_short_uuid()
    client_folder_path = os.path.join(CLIENTS_FOLDER, link_uuid)
    os.makedirs(client_folder_path, exist_ok=True)

    if 'device_uuid' not in session:
        session['device_uuid'] = str(uuid.uuid4())

    session.permanent = True
    device_uuid = session['device_uuid']

    with open(CLIENTFOLDERS_FILE, 'r') as f:
        client_folders = json.load(f)
    
    if not isinstance(client_folders, dict):
        client_folders = {}

    client_folders[link_uuid] = device_uuid
    with open(CLIENTFOLDERS_FILE, 'w') as f:
        json.dump(client_folders, f)

    client_link = url_for('receive_file', link_uuid=link_uuid, _external=True)
    return jsonify({
        'link': url_for('host', link_uuid=link_uuid, _external=True),
        'client_link': client_link
    })

def is_allowed_link(link_uuid):
    device_uuid = session.get('device_uuid')
    if not device_uuid:
        return False

    with open(CLIENTFOLDERS_FILE, 'r') as f:
        client_folders = json.load(f)
    return client_folders.get(link_uuid) == device_uuid

def is_valid_link(link_uuid):
    with open(CLIENTFOLDERS_FILE, 'r') as f:
        client_folders = json.load(f)
    return link_uuid in client_folders

@app.route('/host/<link_uuid>')
def host(link_uuid):
    if not is_allowed_link(link_uuid):
        return render_template('no_access.html'), 403
    return render_template('host.html', link_uuid=link_uuid)

@app.route('/client/<link_uuid>')
def receive_file(link_uuid):
    if not is_valid_link(link_uuid):
        return render_template('invalid_link.html'), 404
    return render_template('send.html', link_uuid=link_uuid)

@app.route('/files/<link_uuid>/list')
def list_files(link_uuid):
    if not is_allowed_link(link_uuid):
        return render_template('no_access.html'), 403
    client_path = os.path.join(CLIENTS_FOLDER, link_uuid)
    if not os.path.exists(client_path):
        return jsonify([])

    files = []
    file_info_path = os.path.join(client_path, 'file_info.json')
    if os.path.exists(file_info_path):
        with open(file_info_path, 'r') as f:
            files = json.load(f)
    return jsonify(files)

@app.route('/files/<link_uuid>/<filename>')
def download_file(link_uuid, filename):
    if not is_allowed_link(link_uuid):
        return render_template('no_access.html'), 403
    directory = os.path.join(CLIENTS_FOLDER, link_uuid)
    return send_from_directory(directory, filename, as_attachment=True)

@app.route('/upload/<link_uuid>', methods=['POST'])
def upload_file(link_uuid):
    if not is_valid_link(link_uuid):
        return render_template('invalid_link.html'), 404
    client_path = os.path.join(CLIENTS_FOLDER, link_uuid)
    if not os.path.exists(client_path):
        os.makedirs(client_path)

    file = request.files['file']
    file_id = str(uuid.uuid4())
    original_name = file.filename
    extension = original_name.rsplit('.', 1)[-1] if '.' in original_name else ''
    save_filename = f"{file_id}.{extension}" if extension else file_id

    file_path = os.path.join(client_path, save_filename)
    file.save(file_path)

    file_info_path = os.path.join(client_path, 'file_info.json')
    file_data = {'id': file_id, 'name': original_name, 'ext': extension}
    if os.path.exists(file_info_path):
        with open(file_info_path, 'r') as f:
            current_data = json.load(f)
        current_data.append(file_data)
    else:
        current_data = [file_data]
    with open(file_info_path, 'w') as f:
        json.dump(current_data, f)

    return jsonify({"success": True, "file_id": file_id, "original_name": original_name})

@app.route('/end_session/<link_uuid>')
def end_session(link_uuid):
    if not is_allowed_link(link_uuid):
        return render_template('no_access.html'), 403

    client_folder_path = os.path.join(CLIENTS_FOLDER, link_uuid)
    if os.path.exists(client_folder_path):
        shutil.rmtree(client_folder_path)

    with open(CLIENTFOLDERS_FILE, 'r') as f:
        client_folders = json.load(f)
    client_folders.pop(link_uuid, None)
    with open(CLIENTFOLDERS_FILE, 'w') as f:
        json.dump(client_folders, f)

    return redirect(url_for('main_page'))

@socketio.on('connect_to_room')
def connect_to_room(data):
    link_uuid = data.get('link_uuid')
    if is_allowed_link(link_uuid):
        join_room(link_uuid)
    else:
        emit('invalid_link', {'error': 'Invalid link'})

@socketio.on('file_upload')
def handle_file_upload(data):
    link_uuid = data.get('link_uuid')
    if not is_allowed_link(link_uuid):
        emit('invalid_link', {'error': 'Invalid link'})
        return

    filename = data.get('filename')
    file_data = data.get('file_data').encode()

    file_id = str(uuid.uuid4())
    file_ext = secure_filename(filename).split('.')[-1] if '.' in filename else ''
    save_filename = f"{file_id}{f'.{file_ext}' if file_ext else ''}"

    client_path = os.path.join(CLIENTS_FOLDER, link_uuid)
    if not os.path.exists(client_path):
        os.makedirs(client_path)

    file_path = os.path.join(client_path, save_filename)
    with open(file_path, 'wb') as f:
        f.write(file_data)

    file_info_path = os.path.join(client_path, 'file_info.json')
    file_metadata = {'id': file_id, 'name': filename, 'ext': file_ext}
    if os.path.exists(file_info_path):
        with open(file_info_path, 'r') as f:
            current_data = json.load(f)
        current_data.append(file_metadata)
    else:
        current_data = [file_metadata]
    with open(file_info_path, 'w') as f:
        json.dump(current_data, f)

    emit('file_received', {
        'id': file_id,
        'name': filename,
        'ext': file_ext,
        'link_uuid': link_uuid
    }, room=link_uuid)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=80, debug=False)
