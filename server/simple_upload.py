import os
from flask import Flask, flash, request, redirect
from werkzeug.utils import secure_filename
from datetime import datetime
import time
import argparse


UPLOAD_FOLDER = './files'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'xxxx'


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_upload_folder():
    folder = os.path.join(app.config['UPLOAD_FOLDER'], datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d'))
    if not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    return folder


def save_a_file(f):
    if f and f.filename and allowed_file(f.filename):
        filename = secure_filename(f.filename)
        filepath = os.path.join(get_upload_folder(), filename)
        if os.path.exists(filepath):
            filename = f'{time.time()}-{filename}'
            filepath = os.path.join(get_upload_folder(), filename)
        f.save(filepath)
        return filename
    return 'field'


@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'files' not in request.files:
            flash('No files part')
            return redirect(request.url)
        files = request.files.getlist('files')
        uploaded_file_list = f"""
        <ul><li>{'</li><li>'.join([f.filename + '=>' + save_a_file(f) for f in files])}</li></ul>
        """
    else:
        uploaded_file_list = ''

    return f'''
<!doctype html>
<html>
<head>
    <title>Upload new File</title>
    <style>
        .hidden {{
            display: none;
        }}
        .container {{
            font-family: Cascadia Code, Source Code Pro;
            display: flex;
            flex-flow: column nowrap;
            justify-content: center;
            flex-basis: content;
            gap: 3vw;
            max-width: 50%;
            margin: auto;
            text-align: center;
            font-size: 2vw;
        }}
        .exts {{
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 1vw;
        }}
        .ext {{
            height: 3vw;
            width: 5vw;
            vertical-align: baseline;
            border-radius: .8vw;
            background: #a3d2ff;
            line-height: 3vw;
        }}
        input {{
            font-size: 1em;
        }}
        input[type=file]::file-selector-button {{
            font-size: 1em;
        }}
        @media only screen and (max-width: 1080px) {{
            .container {{
                max-width: 100%;
                font-size: 5vw;
            }}
            .ext {{
                height: 8vw;
                width: 20vw;
                border-radius: 2vw;
                line-height: 8vw;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Upload New File</h1>
        <div class="{'' if uploaded_file_list else 'hidden'}">
            {uploaded_file_list}
        </div>
        <div class="exts-container">
            <div class="exts"><div class="ext">{'</div><div class="ext">'.join(ALLOWED_EXTENSIONS)}</div></div>
        </div>
        <div class="form-container">
            <form method=post enctype=multipart/form-data>
                <input type=file name=files multiple>
                <input type=submit value=Upload>
            </form>
        </div>
    </div>
    </body>
</html>'''


parser = argparse.ArgumentParser()
parser.add_argument('-l', '--listen', default='0.0.0.0')
parser.add_argument('-p', '--port', type=int, default=5000)
parser.add_argument('--ext', dest='exts', nargs='+', type=str, default=[])
parser.add_argument('-d', '--debug', dest='debug', action='store_true')
args = parser.parse_args()

ALLOWED_EXTENSIONS.update(args.exts)

app.run(args.listen, args.port, debug=args.debug)
