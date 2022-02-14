"""
!!! Never use it in public production.
!!! Never use it in public production.
!!! Never use it in public production.
!!! Never use it in public production.
!!! Never use it in public production.
!!! Never use it in public production.

"""
import datetime
import os
import argparse
import flask
import pyotp
import qrcode
import werkzeug.datastructures


def init_otp(args):
    if os.path.exists(args.totp_file):
        if input(f"'{args.totp_file}' exists! Do you want to rewrite it?[Yy/Nn]:").lower().strip() != 'y':
            print('Nothing happened!')
            return
    key = pyotp.random_base32()
    with open(args.totp_file, 'w+') as f:
        f.write(key)
    name = args.name if args.name else os.path.basename(args.totp_file)
    issuer = args.issuer
    uri = pyotp.TOTP(key).provisioning_uri(name=name, issuer_name=issuer)
    print('Your uri:')
    print(uri)
    if args.output_qrcode:
        qrcode.make(uri).save(args.output_qrcode)
        print(f'qrcode saved to: {args.output_qrcode}')


def verify_otp(args):
    with open(args.totp_file) as f:
        otp = pyotp.TOTP(f.read().strip())

    if args.token:
        if otp.verify(args.token, valid_window=args.valid_window):
            print('right!')
        else:
            print('wrong!')
    else:
        while True:
            token = input('token or exit:')
            if token.lower() == 'exit':
                print('bye!')
                return
            if otp.verify(token, valid_window=args.valid_window):
                print('right!')
            else:
                print('wrong!')


def start_server(args):
    app = flask.Flask(__name__)
    app.config['SECRET_KEY'] = 'dasjkildjasn193u1908dsjiofajj#$*(4981ijdJSIODN'
    app.config['MAX_AUTHORIZED'] = datetime.timedelta(days=1).total_seconds()
    with open(args.totp_file) as f:
        otp = pyotp.TOTP(f.read().strip())
    if not os.path.exists(args.dir_path) or not os.path.isdir(args.dir_path):
        raise ValueError(f"{args.dir_path} does not exist!")
    app.config['dir_path'] = os.path.abspath(args.dir_path)

    def verify(token):
        return otp.verify(token, valid_window=args.valid_window)

    def abort():
        www_authenticate = werkzeug.datastructures.WWWAuthenticate('Basic')
        return flask.abort(401, www_authenticate=www_authenticate)

    @app.route('/<path:path>', methods=['GET'])
    def main(path):
        authorized = flask.session.get('authorized', None)
        if authorized and datetime.datetime.now().timestamp() - authorized['time'] > app.config['MAX_AUTHORIZED']:
            flask.session.pop('authorized', None)
            return abort()
        elif flask.request.authorization:
            if not verify(flask.request.authorization.password):
                return abort()
            authorized = {'time': datetime.datetime.now().timestamp()}
            flask.session['authorized'] = authorized
        elif not authorized:
            return abort()
        real_path = os.path.abspath(os.path.join(app.config['dir_path'], path))
        if os.path.relpath(real_path, app.config['dir_path']).startswith('..'):
            return 'fuck you!'
        if not os.path.exists(real_path):
            return 'fuck you!'
        with open(real_path) as f:
            return f.read()

    app.run(args.listen, args.port, debug=args.debug)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--totp-file', required=True)
    parser.add_argument('-w', '--valid-window', type=int, default=0)
    sub_parsers = parser.add_subparsers()

    start_parser = sub_parsers.add_parser('start')
    start_parser.set_defaults(command=start_server)
    start_parser.add_argument('-l', '--listen', default='0.0.0.0')
    start_parser.add_argument('-p', '--port', type=int, default=5000)
    start_parser.add_argument('-d', '--debug', dest='debug', action='store_true')
    start_parser.add_argument('dir_path')

    init_parser = sub_parsers.add_parser('init')
    init_parser.set_defaults(command=init_otp)
    init_parser.add_argument('-n', '--name')
    init_parser.add_argument('-i', '--issuer', default='simple.secret')
    init_parser.add_argument('-o', '--output-qrcode')

    verify_parser = sub_parsers.add_parser('verify')
    verify_parser.set_defaults(command=verify_otp)
    ex_group = verify_parser.add_mutually_exclusive_group(required=True)
    ex_group.add_argument('-t', '--token')
    ex_group.add_argument('-r', '--repl', action='store_true')

    args_ = parser.parse_args()
    args_.command(args_)
