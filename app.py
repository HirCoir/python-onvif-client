import os
import re
import json
import uuid
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
import psutil
import math

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config['SESSION_COOKIE_SECURE'] = False  # Change to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# Diccionario para almacenar las cámaras configuradas
cameras = {}

# Diccionario para almacenar los procesos de grabación
recording_processes = {}

# Ruta del archivo de configuración JSON
CONFIG_FILE = 'camera_config.json'

def save_camera_config():
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cameras, f)

def load_camera_config():
    global cameras
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            cameras = json.load(f)
    
    # Asegurarse de que cada cámara tenga un ID único
    for camera_name, camera in cameras.items():
        if 'id' not in camera:
            camera['id'] = str(uuid.uuid4())
    
    save_camera_config()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def generar_vista_previa(video_path):
    try:
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        if ret:
            _, buffer = cv2.imencode('.jpg', frame)
            return base64.b64encode(buffer).decode('utf-8')
    except Exception as e:
        print(f"Error al generar vista previa para {video_path}: {str(e)}")
    return None

def listar_videos(page=1):
    videos = []
    for root, dirs, files in os.walk(config.DIRECTORIO_VIDEOS):
        for filename in files:
            if filename.lower().endswith(('.mp4', '.avi', '.mov')):
                file_path = os.path.join(root, filename)
                absolute_path = os.path.abspath(file_path)
                file_size = os.path.getsize(file_path)
                vista_previa = generar_vista_previa(file_path)
                videos.append({
                    'nombre': filename,
                    'ruta_absoluta': absolute_path,
                    'tamaño': file_size,
                    'fecha_modificacion': datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S'),
                    'vista_previa': vista_previa,
                    'url': url_for('serve_video', filename=os.path.relpath(file_path, config.DIRECTORIO_VIDEOS))
                })
    
    videos.sort(key=lambda x: x['fecha_modificacion'], reverse=True)
    total_pages = math.ceil(len(videos) / config.VIDEOS_POR_PAGINA)
    start = (page - 1) * config.VIDEOS_POR_PAGINA
    end = start + config.VIDEOS_POR_PAGINA
    return videos[start:end], total_pages

@app.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    videos, total_pages = listar_videos(page)
    return render_template('dashboard.html', videos=videos, page=page, total_pages=total_pages)

@app.route('/get_videos')
@login_required
def get_videos():
    page = request.args.get('page', 1, type=int)
    videos, total_pages = listar_videos(page)
    return jsonify({'videos': videos, 'total_pages': total_pages})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in config.USUARIOS and config.USUARIOS[username] == password:
            session.permanent = True
            session['username'] = username
            flash('Inicio de sesión exitoso', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/rename_video', methods=['POST'])
@login_required
def rename_video():
    old_path = request.form['old_path']
    new_name = secure_filename(request.form['nuevo_nombre'])
    
    old_full_path = os.path.join(config.DIRECTORIO_VIDEOS, old_path)
    new_full_path = os.path.join(os.path.dirname(old_full_path), new_name)
    
    if os.path.exists(new_full_path):
        return jsonify({'success': False, 'message': 'Ya existe un archivo con ese nombre'}), 400
    
    try:
        os.rename(old_full_path, new_full_path)
        return jsonify({'success': True, 'message': f"Video renombrado de '{old_path}' a '{new_name}'"})
    except OSError as e:
        return jsonify({'success': False, 'message': f"Error al renombrar el archivo: {str(e)}"}), 500

@app.route('/delete_video', methods=['POST'])
@login_required
def delete_video():
    video_path = request.form['video_path']
    full_path = os.path.join(config.DIRECTORIO_VIDEOS, video_path)
    try:
        os.remove(full_path)
        flash(f"Video '{video_path}' eliminado.", 'success')
    except OSError as e:
        flash(f"Error al eliminar el video: {str(e)}", 'error')
    return redirect(url_for('index'))

@app.route('/video/<path:filename>')
@login_required
def serve_video(filename):
    video_path = os.path.join(config.DIRECTORIO_VIDEOS, filename)
    
    if not os.path.exists(video_path):
        abort(404)
    
    range_header = request.headers.get('Range', None)
    byte1, byte2 = 0, None
    if range_header:
        match = re.search(r'(\d+)-(\d*)', range_header)
        groups = match.groups()

        if groups[0]:
            byte1 = int(groups[0])
        if groups[1]:
            byte2 = int(groups[1])

    chunk_size = 1024 * 1024
    file_size = os.stat(video_path).st_size
    if byte2 is None or byte2 >= file_size:
        byte2 = file_size - 1
    length = byte2 - byte1 + 1

    def generate():
        with open(video_path, "rb") as video_file:
            video_file.seek(byte1)
            remaining = length
            while True:
                chunk = video_file.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
                if remaining <= 0:
                    break

    mime_type, _ = mimetypes.guess_type(filename)
    headers = {
        'Content-Type': mime_type,
        'Accept-Ranges': 'bytes',
        'Content-Range': f'bytes {byte1}-{byte2}/{file_size}',
        'Content-Length': str(length)
    }
    return Response(generate(), 206, headers)

@app.route('/download/<path:filename>')
@login_required
def download_video(filename):
    return send_file(os.path.join(config.DIRECTORIO_VIDEOS, filename), as_attachment=True)

@app.route('/recording')
@login_required
def recording():
    return render_template('recording.html', cameras=cameras)

@app.route('/add_camera', methods=['POST'])
@login_required
def add_camera():
    camera_url = request.form['camera_url']
    camera_name = request.form['camera_name']
    
    if camera_name in cameras:
        flash('Ya existe una cámara con ese nombre', 'error')
        return redirect(url_for('recording'))
    
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                 'stream=codec_type', '-of', 'default=noprint_wrappers=1:nokey=1',
                                 camera_url], 
                                capture_output=True, text=True, timeout=10)
        
        if 'video' not in result.stdout:
            flash('No se pudo detectar un flujo de video en la URL proporcionada', 'error')
            return redirect(url_for('recording'))
    except subprocess.TimeoutExpired:
        flash('Tiempo de espera agotado al intentar conectar con la cámara', 'error')
        return redirect(url_for('recording'))
    except subprocess.CalledProcessError:
        flash('Error al conectar con la cámara', 'error')
        return redirect(url_for('recording'))
    
    preview_image = capture_camera_preview(camera_url)
    
    camera_id = str(uuid.uuid4())
    cameras[camera_name] = {
        'id': camera_id,
        'url': camera_url,
        'recording': False,
        'loop_minutes': 60,
        'save_path': config.DIRECTORIO_VIDEOS,
        'preview': preview_image
    }
    
    save_camera_config()
    flash('Cámara agregada exitosamente', 'success')
    return redirect(url_for('recording'))

@app.route('/update_camera', methods=['POST'])
@login_required
def update_camera():
    camera_name = request.form['camera_name']
    new_name = request.form['new_name']
    camera_url = request.form['camera_url']
    loop_minutes = int(request.form['loop_minutes'])
    save_path = request.form['save_path']
    
    if camera_name not in cameras:
        flash('Cámara no encontrada', 'error')
        return redirect(url_for('recording'))
    
    if new_name != camera_name and new_name in cameras:
        flash('Ya existe una cámara con ese nombre', 'error')
        return redirect(url_for('recording'))
    
    preview_image = capture_camera_preview(camera_url)
    
    if new_name != camera_name:
        cameras[new_name] = cameras.pop(camera_name)
    
    cameras[new_name].update({
        'url': camera_url,
        'loop_minutes': loop_minutes,
        'save_path': save_path,
        'preview': preview_image
    })
    
    save_camera_config()
    flash('Configuración de cámara actualizada', 'success')
    return redirect(url_for('recording'))

@app.route('/delete_camera', methods=['POST'])
@login_required
def delete_camera():
    camera_name = request.form['camera_name']
    
    if camera_name not in cameras:
        flash('Cámara no encontrada', 'error')
        return redirect(url_for('recording'))
    
    # Detener la grabación si está en curso
    stop_recording_for_camera(camera_name)
    
    # Esperar a que el proceso de grabación termine completamente
    if camera_name in recording_processes:
        recording_processes[camera_name].join()
        del recording_processes[camera_name]
    
    del cameras[camera_name]
    save_camera_config()
    flash(f'Cámara "{camera_name}" eliminada exitosamente', 'success')
    return redirect(url_for('recording'))

@app.route('/start_recording', methods=['POST'])
@login_required
def start_recording():
    camera_name = request.form['camera_name']
    
    if camera_name not in cameras:
        flash('Cámara no encontrada', 'error')
        return redirect(url_for('recording'))
    
    if cameras[camera_name]['recording']:
        flash('La grabación ya está en curso', 'warning')
        return redirect(url_for('recording'))
    
    cameras[camera_name]['recording'] = True
    save_camera_config()
    recording_thread = threading.Thread(target=record_camera, args=(camera_name,))
    recording_thread.start()
    recording_processes[camera_name] = recording_thread
    
    flash(f'Grabación iniciada para {camera_name}', 'success')
    return redirect(url_for('recording'))

@app.route('/stop_recording', methods=['POST'])
@login_required
def stop_recording():
    camera_name = request.form['camera_name']
    
    if camera_name not in cameras:
        flash('Cámara no encontrada', 'error')
        return redirect(url_for('recording'))
    
    if not cameras[camera_name]['recording']:
        flash('La cámara no está grabando', 'warning')
        return redirect(url_for('recording'))
    
    stop_recording_for_camera(camera_name)
    
    flash(f'Grabación detenida para {camera_name}', 'success')
    return redirect(url_for('recording'))

@app.route('/get_video_info', methods=['POST'])
@login_required
def get_video_info():
    video_path = request.form['video_path']
    full_path = os.path.join(config.DIRECTORIO_VIDEOS, video_path)
    
    if not os.path.exists(full_path):
        return jsonify({'success': False, 'message': 'El archivo de video no existe'}), 404
    
    try:
        # Obtener información del video usando ffprobe
        result = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', full_path],
                                capture_output=True, text=True)
        video_info = json.loads(result.stdout)
        
        # Extraer la información relevante
        duration = float(video_info['format']['duration'])
        size = int(video_info['format']['size'])
        
        return jsonify({
            'success': True,
            'duration': f"{duration:.2f} segundos",
            'size': f"{size / (1024 * 1024):.2f} MB",
            'path': full_path
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error al obtener información del video: {str(e)}"}), 500

def capture_camera_preview(camera_url):
    try:
        cap = cv2.VideoCapture(camera_url)
        ret, frame = cap.read()
        if ret:
            _, buffer = cv2.imencode('.jpg', frame)
            return base64.b64encode(buffer).decode('utf-8')
    except Exception as e:
        print(f"Error al capturar vista previa de la cámara: {str(e)}")
    return None

def record_camera(camera_name):
    camera = cameras[camera_name]
    process_id = f"ffmpeg_{camera['id']}"
    
    while camera['recording']:
        start_time = time.time()
        output_filename = f"{camera_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        output_path = os.path.join(camera['save_path'], output_filename)
        
        # Crear el directorio si no existe
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        ffmpeg_command = [
            'ffmpeg',
            '-rtsp_transport', 'tcp',
            '-i', camera['url'],
            '-t', str(camera['loop_minutes'] * 60),
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-c:a', 'aac',
            '-f', 'mp4',
            '-movflags', '+faststart',
            output_path
        ]
        
        try:
            process = subprocess.Popen(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            recording_processes[process_id] = process
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                print(f"Error durante la grabación de {camera_name}: {stderr.decode()}")
                
            # Si el archivo de salida existe y tiene un tamaño mayor a 0, lo mantenemos
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"Se guardó un video: {output_filename}")
            else:
                os.remove(output_path)
                print(f"Se eliminó un archivo vacío: {output_filename}")
            
        except Exception as e:
            print(f"Excepción durante la grabación de {camera_name}: {str(e)}")
        finally:
            if process_id in recording_processes:
                del recording_processes[process_id]
        
        # Esperar hasta que se complete el tiempo de grabación o hasta que se detenga la grabación
        while time.time() - start_time < camera['loop_minutes'] * 60 and camera['recording']:
            time.sleep(1)
        
        if not camera['recording']:
            break
    
    print(f"Grabación detenida para {camera_name}")

def stop_recording_for_camera(camera_name):
    if camera_name in cameras:
        cameras[camera_name]['recording'] = False
        save_camera_config()
        
        process_id = f"ffmpeg_{cameras[camera_name]['id']}"
        if process_id in recording_processes:
            process = recording_processes[process_id]
            process.terminate()
            process.wait()
            del recording_processes[process_id]
        
        # Esperar a que el proceso de grabación termine
        if camera_name in recording_processes:
            recording_processes[camera_name].join()
            del recording_processes[camera_name]

def start_recording_for_all_cameras():
    for camera_name, camera in cameras.items():
        if camera['recording']:
            recording_thread = threading.Thread(target=record_camera, args=(camera_name,))
            recording_thread.start()
            recording_processes[camera_name] = recording_thread

def check_recording_processes():
    while True:
        for camera_name, camera in list(cameras.items()):
            process_id = f"ffmpeg_{camera['id']}"
            if camera['recording'] and process_id not in recording_processes:
                print(f"Reiniciando grabación para {camera_name}")
                recording_thread = threading.Thread(target=record_camera, args=(camera_name,))
                recording_thread.start()
                recording_processes[camera_name] = recording_thread
            elif not camera['recording'] and process_id in recording_processes:
                print(f"Deteniendo grabación para {camera_name}")
                stop_recording_for_camera(camera_name)
        
        # Limpiar procesos de cámaras eliminadas
        for process_id in list(recording_processes.keys()):
            if process_id.startswith("ffmpeg_"):
                camera_id = process_id.split("_")[1]
                if not any(camera['id'] == camera_id for camera in cameras.values()):
                    print(f"Deteniendo proceso huérfano: {process_id}")
                    process = recording_processes[process_id]
                    process.terminate()
                    process.wait()
                    del recording_processes[process_id]
        
        time.sleep(10)  # Verificar cada 10 segundos

@app.route('/generate_timeline/<path:filename>')
@login_required
def generate_timeline(filename):
    video_path = os.path.join(config.DIRECTORIO_VIDEOS, filename)
    if not os.path.exists(video_path):
        abort(404)

    # Crear un directorio temporal para los frames
    temp_dir = os.path.join(config.DIRECTORIO_VIDEOS, 'temp_frames', os.path.splitext(filename)[0])
    os.makedirs(temp_dir, exist_ok=True)

    # Generar frames
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    frames = []
    for i in range(0, total_frames, int(fps)):  # Capturar un frame por segundo
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if ret:
            frame_filename = f"frame_{i}.jpg"
            frame_path = os.path.join(temp_dir, frame_filename)
            cv2.imwrite(frame_path, frame)
            frames.append({
                'path': os.path.join('temp_frames', os.path.splitext(filename)[0], frame_filename),
                'time': i / fps
            })

    cap.release()

    return render_template('timeline.html', video_filename=filename, frames=frames, duration=duration)

@app.route('/get_timeline_frames/<path:filename>')
@login_required
def get_timeline_frames(filename):
    video_path = os.path.join(config.DIRECTORIO_VIDEOS, filename)
    if not os.path.exists(video_path):
        abort(404)

    temp_dir = os.path.join(config.DIRECTORIO_VIDEOS, 'temp_frames', os.path.splitext(filename)[0])
    frames = []
    for frame_file in sorted(os.listdir(temp_dir)):
        if frame_file.endswith('.jpg'):
            frame_number = int(frame_file.split('_')[1].split('.')[0])
            frames.append({
                'path': os.path.join('temp_frames', os.path.splitext(filename)[0], frame_file),
                'time': frame_number / 30  # Asumiendo 30 FPS, ajusta según sea necesario
            })

    return jsonify(frames)

if __name__ == '__main__':
    # Crear el directorio de videos si no existe
    os.makedirs(config.DIRECTORIO_VIDEOS, exist_ok=True)
    load_camera_config()
    start_recording_for_all_cameras()
    threading.Thread(target=check_recording_processes, daemon=True).start()
    app.run(debug=False, host='0.0.0.0')
