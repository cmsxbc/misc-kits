import os
import hashlib
import re
import time
import argparse
from datetime import datetime

import flask
from flask import Flask, flash, request, redirect
import mimetypes
import markupsafe

import magic


UPLOAD_FOLDER = './files'
ALLOWED_MIMES = {mimetypes.types_map[f".{ext}"] for ext in ('txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov')}
VIEWER_URL = ''

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
        .plaintext-container {
            margin: 0 auto 1em auto;
            font-size: 1vw;
        }
        .plaintext-container summary {
            font-size: 2vw;
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


def link_latest_folder():
    folder = os.path.join(app.config['UPLOAD_FOLDER'], datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d'))
    latest_folder = os.path.join(app.config['UPLOAD_FOLDER'], "latest")
    if os.path.islink(latest_folder) and os.path.realpath(latest_folder) == os.path.realpath(folder):
        return
    if os.path.lexists(latest_folder):
        os.unlink(latest_folder)
    os.symlink(os.path.relpath(folder, os.path.dirname(latest_folder)), latest_folder)  # ,target_is_directory=True)


def save_a_file(f):
    if f and f.filename:
        buffer = f.stream.read()
        f.stream.seek(0)
        mime = magic.from_buffer(buffer, True)
        if mime not in ALLOWED_MIMES:
            return False, mime
        match deduplicate_file(f.filename, buffer):
            case (reason,):
                return True, reason
            case (filepath, filename):
                f.save(filepath)
                return True, filename
    return False, None


def save_plaintext(content, title=""):
    if title and not re.fullmatch(r"^[\w ]+$", title):
        return False, "Invalid title"
    elif not title:
        title = f"plaintext_{int(time.time())}"
    content = f"""
<html lang="zh-CN">
<title>{markupsafe.escape(title)}</title>
<body>
<pre>
{markupsafe.escape(content)}
</pre>
</body>
</html>
""".encode()
    match deduplicate_file(f"{title}.html", content):
        case(reason, ):
            return True, reason
        case(filepath, filename):
            with open(filepath, 'wb+') as f:
                f.write(content)
            return True, filename
    return False, None


def deduplicate_file(filename: str, content: bytes) -> str | tuple[str, str]:
    filename = re.sub(r'\./\\\s', '_', filename)
    filepath = os.path.join(get_upload_folder(), filename)
    if os.path.exists(filepath):
        upload_md5 = hashlib.md5(content)
        with open(filepath, 'rb') as ef:
            exist_md5 = hashlib.md5(ef.read())
        if exist_md5.digest() == upload_md5.digest():
            return "existed!!!!"
        filename = f'{time.time()}-{filename}'
        filepath = os.path.join(get_upload_folder(), filename)
    return filepath, filename


@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # check if the post request has data
        if 'files' not in request.files and 'plaintext' not in request.form:
            flash('Neither files nor plaintext')
            return redirect(request.url)
        dealt_results = []
        if 'files' in request.files and (files := request.files.getlist('files')):
            if len(files) != 1 or files[0].filename != '':
                for file in files:
                    saved, reason = save_a_file(file)
                    dealt_results.append((file.filename, saved, reason))
        if 'plaintext' in request.form:
            if request.form["plaintext"].strip():
                saved, reason = save_plaintext(request.form["plaintext"], request.form.get("title", ""))
                dealt_results.append(("plaintext", saved, reason))
        if not dealt_results:
            flash('Neither files nor plaintext')
            return redirect(request.url)
        uploaded_file_info_list = []
        for name, saved, reason in dealt_results:
            sname = markupsafe.escape(name)
            sreason = markupsafe.escape(reason)
            if saved:
                uploaded_file_info_list.append(
                    f'<div class="uploadeds"><div class="origin">{sname}</div><div class="saved">{sreason}</div></div>')
            elif reason is None:
                uploaded_file_info_list.append(
                    f'<div class="uploadeds failed"><div class="origin">{sname}</div><div class="reason">{sreason}</div></div>')
            else:
                uploaded_file_info_list.append(
                    f'<div class="uploadeds failed"><div class="origin">{sname}</div><div class="reason">{sreason} is forbidden</div></div>')
        if uploaded_file_info_list:
            link_latest_folder()
        uploaded_file_list = ''.join(uploaded_file_info_list)
    else:
        uploaded_file_list = ''

    viewer = ''
    if VIEWER_URL:
        viewer = f'<div><a href="{VIEWER_URL}">viewer</a></div>'

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
                <input type="file" id="files" name="files" multiple />
                <div class="plaintext-container">
                    <details>
                        <summary>Plain Text</summary>
                        <div>
                            <label for="title">Title</label>
                            <input type="text" name="title" placeholder="title here, can be empty..." />
                        </div>
                        <div>
                            <label for="plaintext">Content</label>
                            <textarea id="plaintext" name="plaintext" rows="5" cols="128"></textarea>
                        </div>
                    </details>
                </div>
                <div class="preview" id="preview">
                </div>
                <div>
                    <input type="submit" class="button" name="submit" value="Submit" />
                </div>
            </form>
        </div>
        {viewer}
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
    parser.add_argument('--viewer-url', dest='viewer_url', default='')
    parser.add_argument('-d', '--debug', dest='debug', action='store_true')
    args = parser.parse_args()

    ALLOWED_MIMES.update(args.mimes)
    ALLOWED_MIMES.update(mimetypes.types_map[f".{ext}"] for ext in args.exts)
    VIEWER_URL = args.viewer_url
    app.run(args.listen, args.port, debug=args.debug)
