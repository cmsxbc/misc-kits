import os
import hashlib
import re
import time
import argparse
from datetime import datetime

import flask
from flask import Flask, flash, request, redirect
import mimetypes

import magic


UPLOAD_FOLDER = './files'
ALLOWED_MIMES = {mimetypes.types_map[f".{ext}"] for ext in ('txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov')}

STYLE = """.hidden {
            display: none !important;
        }
        body {
            font-family: Cascadia Code, Source Code Pro;
        }
        h1 {
            margin: 3vh;
            text-align: center;
            font-size: 5vh;
        }
        .container {
            display: flex;
            flex-flow: column nowrap;
            justify-content: center;
            flex-basis: content;
            gap: 10vh;
            max-width: 50%;
            margin: auto;
            text-align: center;
            font-size: 2vw;
        }
        .uploadeds-container {
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        div.uploadeds {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 1vw 2vw;
            font-size: .4em;
            margin-top: 1vw;
            padding: 1vw 0;
            border-radius: 1vw;
            background: #13f824;
        }
        div.uploadeds.failed {
            background: #f81324;
        }
        div.uploadeds > div {
            padding: 0 1vw;
        }
        div.uploadeds > div.saved {

        }
        div.uploadeds > div.origin {
            color: #aaaaaa;
        }
        div.uploadeds > div + div::before {
            content: "=>";
            color: #ffaacc;
        }
        .mimes {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 1vw;
        }
        .mime {
            height: 3vw;
            min-width: 5vw;
            vertical-align: baseline;
            padding-left: 0.5vw;
            padding-right: 0.5vw;
            border-radius: .8vw;
            background: #a3d2ff;
            line-height: 3vw;
        }
        input[type=submit] {
            border: 0;
            font-family: Cascadia Code, Source Code Pro;
            -webkit-appearance: none;
        }
        .button {
            font-size: 1em;
            width: 5em;
            border-radius: 0.3em;
            background-color: #ffa6dc;
            display: inline-block;
            padding: 0;
        }
        input[type=file] {
            width: 0;
            height: 0;
            opacity: 0;
        }
        .preview li {
            display: flex;
            justify-content: center;
            margin: .5em 0;
            height: 2em;
        }
        .preview p {
            line-height: 2em;
            height: 2em;
            order: 0;
            margin: 0;
            width: 50%;
            text-align: left;
        }
        .no-image p {
            width: 80%;
            text-align: center;
        }
        .preview p.long {
            font-size: .4em;
        }
        .preview img {
            width: 2em;
            height: 2em;
            order: 1;
        }
        .preview img.placeholder {
            opacity: 0;
        }
        @media only screen and (max-width: 1080px) {
            .container {
                max-width: 100%;
                font-size: 5vw;
            }
            .mime {
                height: 8vw;
                min-width: 20vw;
                border-radius: 2vw;
                line-height: 8vw;
            }
        }
"""

SCRIPT = """const $file_input = document.getElementById('files');
        const $preview = document.getElementById('preview');

        function isImage(file) {
            return file.type.startsWith('image');
        }

        $file_input.addEventListener('change', () => {
            if ($file_input.files.length <= 0) {
                return;
            }
            const list = document.createElement('ol');
            preview.innerHTML = '';
            preview.appendChild(list);
            const has_image = Object.values($file_input.files).reduce((p, v) => p || isImage(v), false);
            if (!has_image) {
                preview.classList.add('no-image');
            } else {
                preview.classList.remove('no-image');
            }

            for (const file of $file_input.files) {
                const listItem = document.createElement('li');
                const para = document.createElement('p');
                para.textContent = file.name;
                if (file.name.length > 15) {
                    para.classList.add('long');
                }
                listItem.appendChild(para);
                const image = document.createElement('img');
                if (isImage(file)) {
                    image.src = URL.createObjectURL(file);
                } else if (has_image) {
                    image.classList.add('placeholder')
                }
                if (has_image) {
                    listItem.appendChild(image);
                }
                list.appendChild(listItem);
            }
        });
"""

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'xxxx'


def get_upload_folder():
    folder = os.path.join(app.config['UPLOAD_FOLDER'], datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d'))
    if not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    return folder


def save_a_file(f):
    if f and f.filename:
        buffer = f.stream.read()
        f.stream.seek(0)
        mime = magic.from_buffer(buffer, True)
        if mime not in ALLOWED_MIMES:
            return False, mime
        filename = re.sub(r'\./\\\s', '_', f.filename)
        filepath = os.path.join(get_upload_folder(), filename)
        if os.path.exists(filepath):
            upload_md5 = hashlib.md5(buffer)
            with open(filepath, 'rb') as ef:
                exist_md5 = hashlib.md5(ef.read())
            if exist_md5.digest() == upload_md5.digest():
                return True, "existed!!!!"
            filename = f'{time.time()}-{filename}'
            filepath = os.path.join(get_upload_folder(), filename)
        f.save(filepath)
        return True, filename
    return False, None


@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'files' not in request.files:
            flash('No files part')
            return redirect(request.url)
        files = request.files.getlist('files')
        if not files:
            flash('No files part')
            return redirect(request.url)
        if len(files) == 1 and files[0].filename == '':
            flash('No files part')
            return redirect(request.url)
        uploaded_file_info_list = []
        for file in files:
            saved, reason = save_a_file(file)
            sname = flask.escape(file.filename)
            sreason = flask.escape(reason)
            if saved:
                uploaded_file_info_list.append(f'<div class="uploadeds"><div class="origin">{sname}</div><div class="saved">{sreason}</div></div>')
            elif reason is None:
                uploaded_file_info_list.append(f'<div class="uploadeds failed"><div class="origin">{sname}</div><div class="reason">{sreason}</div></div>')
            else:
                uploaded_file_info_list.append(f'<div class="uploadeds failed"><div class="origin">{sname}</div><div class="reason">{sreason} is forbidden</div></div>')

        uploaded_file_list = ''.join(uploaded_file_info_list)
    else:
        uploaded_file_list = ''

    return f'''
<!doctype html>
<html>
<head>
    <title>Upload New File</title>
    <style>
        {STYLE}
    </style>
</head>
<body>
    <h1>Upload New File</h1>
    <div class="container">
        <div class="uploadeds-container {'' if uploaded_file_list else 'hidden'}">
            {uploaded_file_list}
        </div>
        <div class="mimes-container">
            <div class="mimes"><div class="mime">{'</div><div class="mime">'.join(ALLOWED_MIMES)}</div></div>
        </div>
        <div class="form-container">
            <form method=post enctype=multipart/form-data>
                <div>
                    <label for="files" class="button">Choose</label>
                </div>
                <input type="file" id="files" name="files" multiple>
                <div class="preview" id="preview">
                </div>
                <div>
                    <input type="submit" class="button" name="submit" value="Submit" />
                </div>
            </form>
        </div>
    </div>
    <script>
        {SCRIPT}
    </script>
    </body>
</html>'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--listen', default='0.0.0.0')
    parser.add_argument('-p', '--port', type=int, default=5000)
    parser.add_argument('--ext', dest='exts', action='append', type=str, default=[])
    parser.add_argument('--mime', dest='mimes', action='append', type=str, default=[])
    parser.add_argument('-d', '--debug', dest='debug', action='store_true')
    args = parser.parse_args()

    ALLOWED_MIMES.update(args.mimes)
    ALLOWED_MIMES.update(mimetypes.types_map[f".{ext}"] for ext in args.exts)

    app.run(args.listen, args.port, debug=args.debug)
