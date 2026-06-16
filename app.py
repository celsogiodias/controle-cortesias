import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cortesias-secret-key-2024')

database_url = os.environ.get('DATABASE_URL', 'sqlite:///cortesias.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Cortesia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(50), nullable=False)
    numero = db.Column(db.Integer, nullable=False)
    cor = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='disponivel')

class Emprestimo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cortesia_id = db.Column(db.Integer, db.ForeignKey('cortesia.id'), nullable=False)
    usuario_nome = db.Column(db.String(100), nullable=False)
    usuario_telefone = db.Column(db.String(20), nullable=False)
    data_retirada = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    data_prevista_devolucao = db.Column(db.DateTime, nullable=False)
    data_devolucao_real = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='ativo')
    cortesia = db.relationship('Cortesia', backref='emprestimos', lazy=True)

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

def populate_db():
    if Cortesia.query.first():
        return
    dados = [('Lagoa Silva', 10, '#FFD700'), ('Clube Faisão', 4, '#333333'), ('Usipa', 5, '#C3B091')]
    for categoria, qtd, cor in dados:
        for i in range(1, qtd + 1):
            db.session.add(Cortesia(categoria=categoria, numero=i, cor=cor))
    if not Admin.query.first():
        db.session.add(Admin(username='admin', password=generate_password_hash('admin123')))
    db.session.commit()

with app.app_context():
    db.create_all()
    populate_db()

@app.route('/')
@login_required
def index():
    cortesias = Cortesia.query.all()
    agora = datetime.now(timezone.utc)
    for c in cortesias:
        if c.status == 'emprestada':
            emp = Emprestimo.query.filter_by(cortesia_id=c.id, status='ativo').first()
            c.status_atual = 'atrasada' if (emp and emp.data_prevista_devolucao < agora) else 'emprestada'
        else:
            c.status_atual = 'disponivel'
    return render_template('index.html', cortesias=cortesias)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Admin.query.filter_by(username=request.form.get('username', '')).first()
        if user and check_password_hash(user.password, request.form.get('password', '')):
            login_user(user)
            return redirect(url_for('index'))
        flash('Usuário ou senha inválidos', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/api/emprestar', methods=['POST'])
@login_required
def api_emprestar():
    data = request.get_json()
    if not data: return jsonify({'error': 'Dados inválidos'}), 400
    cortesia_id, nome, telefone = data.get('cortesia_id'), data.get('nome', '').strip(), data.get('telefone', '').strip()
    if not cortesia_id or not nome or not telefone: return jsonify({'error': 'Preencha todos os campos'}), 400
    if Emprestimo.query.filter_by(usuario_telefone=telefone, status='ativo').first(): return jsonify({'error': 'Esta pessoa já possui uma cortesia. Devolva primeiro.'}), 400
    cortesia = Cortesia.query.get(cortesia_id)
    if not cortesia or cortesia.status != 'disponivel': return jsonify({'error': 'Cortesia indisponível'}), 400
    agora, data_limite = datetime.now(timezone.utc), datetime.now(timezone.utc) + timedelta(days=7)
    emp = Emprestimo(cortesia_id=cortesia.id, usuario_nome=nome, usuario_telefone=telefone, data_retirada=agora, data_prevista_devolucao=data_limite, status='ativo')
    cortesia.status = 'emprestada'
    db.session.add(emp)
    db.session.commit()
    return jsonify({'success': True, 'mensagem': f'Empréstimo registrado! Prazo: {data_limite.strftime("%d/%m/%Y")}'})

@app.route('/api/devolver', methods=['POST'])
@login_required
def api_devolver():
    data = request.get_json()
    emp = Emprestimo.query.get(data.get('emprestimo_id')) if data else None
    if not emp: return jsonify({'error': 'Empréstimo não encontrado'}), 404
    cortesia = Cortesia.query.get(emp.cortesia_id)
    emp.status, emp.data_devolucao_real, cortesia.status = 'finalizado', datetime.now(timezone.utc), 'disponivel'
    db.session.commit()
    return jsonify({'success': True, 'mensagem': 'Devolução registrada com sucesso!'})

@app.route('/api/cortesia-status')
@login_required
def api_cortesia_status():
    cortesia = Cortesia.query.get(int(request.args.get('cortesia_id', 0)))
    if not cortesia: return jsonify({'error': 'Cortesia não encontrada'}), 404
    emp = Emprestimo.query.filter_by(cortesia_id=cortesia.id, status='ativo').first()
    agora = datetime.now(timezone.utc)
    dados_emprestimo = {'id': emp.id, 'nome': emp.usuario_nome, 'telefone': emp.usuario_telefone, 'data_retirada': emp.data_retirada.strftime('%d/%m/%Y %H:%M'), 'data_prevista': emp.data_prevista_devolucao.strftime('%d/%m/%Y'), 'dias_atraso': (agora - emp.data_prevista_devolucao).days if emp.data_prevista_devolucao < agora else 0} if emp else None
    return jsonify({'cortesia_id': cortesia.id, 'categoria': cortesia.categoria, 'numero': cortesia.numero, 'status': cortesia.status, 'emprestimo': dados_emprestimo})

@app.route('/dashboard')
@login_required
def dashboard():
    agora = datetime.now(timezone.utc)
    emprestimos_ativos = Emprestimo.query.filter_by(status='ativo').all()
    dados_emprestimos = []
    atrasadas = 0
    for e in emprestimos_ativos:
        c = Cortesia.query.get(e.cortesia_id)
        atrasado = e.data_prevista_devolucao < agora
        if atrasado: atrasadas += 1
        dados_emprestimos.append({'cortesia': f'{c.categoria} #{c.numero}', 'pessoa': e.usuario_nome, 'telefone': e.usuario_telefone, 'retirada': e.data_retirada.strftime('%d/%m/%Y'), 'previsao': e.data_prevista_devolucao.strftime('%d/%m/%Y'), 'atrasado': atrasado, 'dias_atraso': (agora - e.data_prevista_devolucao).days if atrasado else 0})
    return render_template('dashboard.html', total=Cortesia.query.count(), emprestadas=len(emprestimos_ativos), atrasadas=atrasadas, disponiveis=Cortesia.query.filter_by(status='disponivel').count(), emprestimos=dados_emprestimos)

@app.route('/historico')
@login_required
def historico():
    emprestimos = Emprestimo.query.filter_by(status='finalizado').order_by(Emprestimo.data_devolucao_real.desc()).all()
    dados = [{'cortesia': f'{Cortesia.query.get(e.cortesia_id).categoria} #{Cortesia.query.get(e.cortesia_id).numero}', 'pessoa': e.usuario_nome, 'telefone': e.usuario_telefone, 'retirada': e.data_retirada.strftime('%d/%m/%Y'), 'previsao': e.data_prevista_devolucao.strftime('%d/%m/%Y'), 'devolucao': e.data_devolucao_real.strftime('%d/%m/%Y %H:%M') if e.data_devolucao_real else '--'} for e in emprestimos]
    return render_template('historico.html', historico=dados)

if __name__ == '__main__':
    app.run(debug=True)
