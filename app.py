import os
import re
import json
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, Response, jsonify, abort
import cv2
import base64
import mimetypes
import secrets
from werkzeug.utils import secure_filename
import config
import threading
import time
import subprocess
from math import ceil
import tempfile
import shutil

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config['SESSION_COOKIE_SECURE'] = False  # Change to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# Directorio temporal para almacenar las vistas previas
TEMP_PREVIEW_DIR = tempfile.mkdtemp()

def ensure_video_directory_exists():
    if not os.path.exists(config.DIRECTORIO_VIDEOS):
        os.makedirs(config.DIRECTORIO_VIDEOS)

def generate_all_previews():
    ensure_video_directory_exists()
    for filename in os.listdir(config.DIRECTORIO_VIDEOS):
        if filename.lower().endswith(('.mp4', '.avi', '.mov')):
            file_path = os.path.join(config.DIRECTORIO_VIDEOS, filename)
            generate_preview(file_path)

def generate_preview(video_path):
    preview_filename = os.path.basename(video_path) + '.jpg'
    preview_path = os.path.join(TEMP_PREVIEW_DIR, preview_filename)
    
    if os.path.exists(preview_path):
        # Si la vista previa ya existe y el video no ha sido modificado, no la regeneramos
        if os.path.getmtime(video_path) <= os.path.getmtime(preview_path):
            return preview_filename

    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    cap.release()
    
    if ret:
        cv2.imwrite(preview_path, frame)
        return preview_filename
    return None

def listar_videos(page=1, per_page=10):
    videos = []
    for filename in os.listdir(config.DIRECTORIO_VIDEOS):
        if filename.lower().endswith(('.mp4', '.avi', '.mov')):
            file_path = os.path.join(config.DIRECTORIO_VIDEOS, filename)
            file_size = os.path.getsize(file_path)
            preview_filename = generate_preview(file_path)
            videos.append({
                'nombre': filename,
                'tamaño': file_size,
                'fecha_modificacion': datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S'),
                'vista_previa': preview_filename
            })
    
    # Ordenar los videos por fecha de modificación (más reciente primero)
    videos.sort(key=lambda x: x['fecha_modificacion'], reverse=True)
    
    # Calcular el total de páginas
    total_pages = ceil(len(videos) / per_page)
    
    # Obtener los videos para la página actual
    start = (page - 1) * per_page
    end = start + per_page
    paginated_videos = videos[start:end]
    
    return paginated_videos, total_pages

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    videos, total_pages = listar_videos(page=page)
    return render_template('dashboard.html', videos=videos, page=page, total_pages=total_pages)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in config.USUARIOS and config.USUARIOS[username] == password:
            session['username'] = username
            return redirect(url_for('index'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/serve_video/<filename>')
@login_required
def serve_video(filename):
    return send_file(os.path.join(config.DIRECTORIO_VIDEOS, filename))

@app.route('/serve_preview/<filename>')
@login_required
def serve_preview(filename):
    return send_file(os.path.join(TEMP_PREVIEW_DIR, filename))

@app.route('/download_video/<filename>')
@login_required
def download_video(filename):
    return send_file(os.path.join(config.DIRECTORIO_VIDEOS, filename), as_attachment=True)

@app.route('/delete_video', methods=['POST'])
@login_required
def delete_video():
    filename = request.form['filename']
    file_path = os.path.join(config.DIRECTORIO_VIDEOS, filename)
    preview_path = os.path.join(TEMP_PREVIEW_DIR, filename + '.jpg')
    try:
        os.remove(file_path)
        if os.path.exists(preview_path):
            os.remove(preview_path)
        return jsonify({'success': True, 'message': f'Video "{filename}" eliminado correctamente'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error al eliminar el video: {str(e)}'})

@app.route('/rename_video', methods=['POST'])
@login_required
def rename_video():
    old_name = request.form['old_name']
    new_name = request.form['new_name']
    old_path = os.path.join(config.DIRECTORIO_VIDEOS, old_name)
    new_path = os.path.join(config.DIRECTORIO_VIDEOS, new_name)
    old_preview = os.path.join(TEMP_PREVIEW_DIR, old_name + '.jpg')
    new_preview = os.path.join(TEMP_PREVIEW_DIR, new_name + '.jpg')
    try:
        os.rename(old_path, new_path)
        if os.path.exists(old_preview):
            os.rename(old_preview, new_preview)
        return jsonify({'success': True, 'message': f'Video renombrado a "{new_name}"'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error al renombrar el video: {str(e)}'})

@app.route('/get_updated_videos')
@login_required
def get_updated_videos():
    page = request.args.get('page', 1, type=int)
    videos, total_pages = listar_videos(page=page)
    return jsonify({
        'videos': videos,
        'total_pages': total_pages
    })

@app.route('/recording')
@login_required
def recording():
    cameras = load_camera_config()
    return render_template('recording.html', cameras=cameras)

@app.route('/add_camera', methods=['POST'])
@login_required
def add_camera():
    camera_name = request.form['camera_name']
    camera_url = request.form['camera_url']
    cameras = load_camera_config()
    
    if camera_name in cameras:
        flash('Ya existe una cámara con ese nombre', 'error')
    else:
        cameras[camera_name] = {
            'url': camera_url,
            'recording': False,
            'loop_minutes': 60,
            'save_path': os.path.join(config.DIRECTORIO_VIDEOS, camera_name)
        }
        save_camera_config(cameras)
        flash('Cámara agregada correctamente', 'success')
    
    return redirect(url_for('recording'))

@app.route('/update_camera', methods=['POST'])
@login_required
def update_camera():
    camera_name = request.form['camera_name']
    new_name = request.form['new_name']
    camera_url = request.form['camera_url']
    loop_minutes = int(request.form['loop_minutes'])
    save_path = request.form['save_path']
    
    cameras = load_camera_config()
    
    if camera_name in cameras:
        if new_name != camera_name and new_name in cameras:
            flash('Ya existe una cámara con ese nombre', 'error')
        else:
            camera_config = cameras.pop(camera_name)
            camera_config.update({
                'url': camera_url,
                'loop_minutes': loop_minutes,
                'save_path': save_path
            })
            cameras[new_name] = camera_config
            save_camera_config(cameras)
            flash('Configuración de cámara actualizada', 'success')
    else:
        flash('Cámara no encontrada', 'error')
    
    return redirect(url_for('recording'))

@app.route('/delete_camera', methods=['POST'])
@login_required
def delete_camera():
    camera_name = request.form['camera_name']
    cameras = load_camera_config()
    
    if camera_name in cameras:
        del cameras[camera_name]
        save_camera_config(cameras)
        flash('Cámara eliminada correctamente', 'success')
    else:
        flash('Cámara no encontrada', 'error')
    
    return redirect(url_for('recording'))

@app.route('/start_recording', methods=['POST'])
@login_required
def start_recording():
    camera_name = request.form['camera_name']
    cameras = load_camera_config()
    
    if camera_name in cameras and not cameras[camera_name]['recording']:
        cameras[camera_name]['recording'] = True
        save_camera_config(cameras)
        # Aquí iría el código para iniciar la grabación
        flash(f'Grabación iniciada para la cámara {camera_name}', 'success')
    else:
        flash('Cámara no encontrada o ya está grabando', 'error')
    
    return redirect(url_for('recording'))

@app.route('/stop_recording', methods=['POST'])
@login_required
def stop_recording():
    camera_name = request.form['camera_name']
    cameras = load_camera_config()
    
    if camera_name in cameras and cameras[camera_name]['recording']:
        cameras[camera_name]['recording'] = False
        save_camera_config(cameras)
        # Aquí iría el código para detener la grabación
        flash(f'Grabación detenida para la cámara {camera_name}', 'success')
    else:
        flash('Cámara no encontrada o no está grabando', 'error')
    
    return redirect(url_for('recording'))

def load_camera_config():
    if os.path.exists('camera_config.json'):
        with open('camera_config.json', 'r') as f:
            return json.load(f)
    return {}

def save_camera_config(cameras):
    with open('camera_config.json', 'w') as f:
        json.dump(cameras, f, indent=2)

def cleanup_temp_dir():
    if os.path.exists(TEMP_PREVIEW_DIR):
        shutil.rmtree(TEMP_PREVIEW_DIR)

if __name__ == '__main__':
    generate_all_previews()  # Generar todas las vistas previas al iniciar
    app.run(debug=False, host='0.0.0.0')
    atexit.register(cleanup_temp_dir)  # Limpiar el directorio temporal al cerrar la aplicación
