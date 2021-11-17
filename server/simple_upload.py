import os
from flask import Flask, flash, request, redirect
from werkzeug.utils import secure_filename
from datetime import datetime
import time
import argparse


UPLOAD_FOLDER = './files'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov'}

STYLE = """.hidden {
            display: none;
        }
        .container {
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
        }
        .exts {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 1vw;
        }
        .ext {
            height: 3vw;
            width: 5vw;
            vertical-align: baseline;
            border-radius: .8vw;
            background: #a3d2ff;
            line-height: 3vw;
        }
        input[type=submit] {
            border: 0;
            font-family: Cascadia Code, Source Code Pro;
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
        .preview p.long {
            font-size: .4em;
        }
        .preview img {
            width: 2em;
            height: 2em;
            order: 1;
        }
        @media only screen and (max-width: 1080px) {
            .container {
                max-width: 100%;
                font-size: 5vw;
            }
            .ext {
                height: 8vw;
                width: 20vw;
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
            const list = document.createElement('ol');
            preview.innerHTML = '';
            preview.appendChild(list);
            for (const file of $file_input.files) {
                const listItem = document.createElement('li');
                const para = document.createElement('p');
                para.textContent = file.name;
                if (file.name.length > 15) {
                    para.classList.add('long');
                }
                listItem.appendChild(para);
                if(isImage(file)) {
                    const image = document.createElement('img');
                    image.src = URL.createObjectURL(file);
                    listItem.appendChild(image);
                }

                list.appendChild(listItem);
            }
        });
"""

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
        if not files:
            flash('No files part')
            return redirect(request.url)
        if len(files) == 1 and files[0].filename == '':
            flash('No files part')
            return redirect(request.url)
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
        {STYLE}
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
                <div>
                    <label for="files" class="button">Choose</label>
                </div>
                <input type="file" id="files" name="files" multiple>
                <div class="preview" id="preview">
                </div>
                <div>
                    <input type="submit" class="button" name="submit"/>
                </div>
            </form>
        </div>
    </div>
    <script>
        {SCRIPT}
    </script>
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
