#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Estacionamento - Frontend Web (Flask)
"""

from flask import Flask, render_template_string, request, redirect, url_for, flash
import sqlite3
from datetime import datetime, timezone, timedelta
import os
import sys
import re

# Fuso horário de Brasília (UTC-3)
BRT = timezone(timedelta(hours=-3))

def agora():
    """Retorna datetime atual no horário de Brasília"""
    return datetime.now(BRT)

def agora_str():
    """Retorna data/hora atual de Brasília como string YYYY-MM-DD HH:MM:SS"""
    return agora().strftime("%Y-%m-%d %H:%M:%S")

def hoje_str():
    """Retorna a data de hoje em Brasília (YYYY-MM-DD)"""
    return agora().strftime("%Y-%m-%d")

def formatar_data(data_str):
    """Formata data do banco para exibição brasileira dd/mm/yyyy HH:mm:ss"""
    if not data_str:
        return "-"
    try:
        s = str(data_str).replace("T", " ").strip()[:19]
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        try:
            dt = datetime.strptime(str(data_str)[:10], "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return str(data_str)

# =============================================
# CONFIGURAÇÃO
# =============================================
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, "estacionamento.db")

app = Flask(__name__)
app.secret_key = "estacionamento_secret_key_2024"

# =============================================
# VALIDAÇÕES PROFISSIONAIS
# =============================================
def validar_placa(placa):
    """Valida placa brasileira (antiga ABC1234 ou Mercosul ABC1D23)"""
    if not placa:
        return False, "Placa é obrigatória."
    p = re.sub(r'[^A-Za-z0-9]', '', placa).upper()
    # Antiga: 3 letras + 4 números
    if re.fullmatch(r'[A-Z]{3}[0-9]{4}', p):
        return True, p
    # Mercosul: 3 letras + 1 número + 1 letra + 2 números
    if re.fullmatch(r'[A-Z]{3}[0-9][A-Z][0-9]{2}', p):
        return True, p
    return False, "Placa inválida. Use o formato ABC1D23 (Mercosul) ou ABC1234 (antiga)."

def validar_cpf(cpf):
    """Valida CPF com dígitos verificadores"""
    if not cpf:
        return True, None  # CPF opcional
    nums = re.sub(r'\D', '', cpf)
    if len(nums) != 11:
        return False, "CPF deve ter 11 dígitos."
    if nums == nums[0] * 11:
        return False, "CPF inválido."
    # 1º dígito
    s = sum(int(nums[i]) * (10 - i) for i in range(9))
    d1 = (s * 10 % 11) % 10
    # 2º dígito
    s = sum(int(nums[i]) * (11 - i) for i in range(10))
    d2 = (s * 10 % 11) % 10
    if int(nums[9]) != d1 or int(nums[10]) != d2:
        return False, "CPF inválido (dígitos verificadores incorretos)."
    formatado = f"{nums[:3]}.{nums[3:6]}.{nums[6:9]}-{nums[9:]}"
    return True, formatado

def validar_nome(nome):
    """Valida nome completo (mínimo 2 palavras, só letras)"""
    if not nome or not nome.strip():
        return False, "Nome é obrigatório."
    n = " ".join(nome.strip().split())
    if len(n) < 3:
        return False, "Nome muito curto."
    if not re.fullmatch(r"[A-Za-zÀ-ÿ\s'.\-]+", n):
        return False, "Nome deve conter apenas letras."
    partes = [p for p in n.split() if len(p) > 1]
    if len(partes) < 2:
        return False, "Informe o nome completo (nome e sobrenome)."
    return True, n.title()

def formatar_valor(valor_str):
    """Converte string de valor para float com 2 casas"""
    if not valor_str:
        return None
    s = str(valor_str).strip().replace("R$", "").replace(" ", "").replace(",", ".")
    try:
        v = float(s)
        if v < 0:
            return None
        return round(v, 2)
    except ValueError:
        return None

# =============================================
# BANCO DE DADOS
# =============================================
def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def inicializar_banco():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vagas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            setor TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('carro', 'moto', 'suv', 'pcd')),
            status TEXT NOT NULL DEFAULT 'livre' CHECK(status IN ('livre', 'ocupada', 'manutencao', 'reservada')),
            valor_hora REAL NOT NULL DEFAULT 10.00,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            placa TEXT NOT NULL UNIQUE,
            modelo TEXT,
            marca TEXT,
            cor TEXT,
            tipo TEXT NOT NULL DEFAULT 'carro' CHECK(tipo IN ('carro', 'moto', 'suv', 'pcd')),
            data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cpf TEXT UNIQUE,
            telefone TEXT,
            email TEXT,
            tipo TEXT NOT NULL DEFAULT 'avulso' CHECK(tipo IN ('avulso', 'mensalista')),
            data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cliente_veiculo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            veiculo_id INTEGER NOT NULL,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
            FOREIGN KEY (veiculo_id) REFERENCES veiculos(id) ON DELETE CASCADE,
            UNIQUE(cliente_id, veiculo_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estacionamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vaga_id INTEGER NOT NULL,
            veiculo_id INTEGER NOT NULL,
            cliente_id INTEGER,
            data_entrada TEXT NOT NULL,
            data_saida TEXT,
            valor_total REAL,
            forma_pagamento TEXT,
            status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo', 'finalizado', 'cancelado')),
            observacao TEXT,
            FOREIGN KEY (vaga_id) REFERENCES vagas(id),
            FOREIGN KEY (veiculo_id) REFERENCES veiculos(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tarifas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            tipo_veiculo TEXT NOT NULL,
            valor_primeira_hora REAL NOT NULL,
            valor_hora_adicional REAL NOT NULL,
            valor_diaria REAL NOT NULL,
            tolerancia_minutos INTEGER DEFAULT 15,
            ativo INTEGER DEFAULT 1
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM vagas")
    if cursor.fetchone()[0] == 0:
        vagas = [
            ('A01', 'A', 'carro', 'livre', 12.00),
            ('A02', 'A', 'carro', 'livre', 12.00),
            ('A03', 'A', 'carro', 'livre', 12.00),
            ('A04', 'A', 'carro', 'livre', 12.00),
            ('A05', 'A', 'carro', 'livre', 12.00),
            ('B01', 'B', 'moto', 'livre', 6.00),
            ('B02', 'B', 'moto', 'livre', 6.00),
            ('B03', 'B', 'moto', 'livre', 6.00),
            ('C01', 'C', 'suv', 'livre', 15.00),
            ('C02', 'C', 'suv', 'livre', 15.00),
            ('P01', 'PCD', 'pcd', 'livre', 0.00),
            ('P02', 'PCD', 'pcd', 'livre', 0.00),
        ]
        cursor.executemany(
            "INSERT INTO vagas (numero, setor, tipo, status, valor_hora) VALUES (?, ?, ?, ?, ?)",
            vagas
        )

        tarifas = [
            ('Tarifa Carro', 'carro', 12.00, 8.00, 50.00, 15),
            ('Tarifa Moto', 'moto', 6.00, 4.00, 25.00, 15),
            ('Tarifa SUV', 'suv', 15.00, 10.00, 70.00, 15),
            ('Tarifa PCD', 'pcd', 0.00, 0.00, 0.00, 15),
        ]
        cursor.executemany(
            "INSERT INTO tarifas (descricao, tipo_veiculo, valor_primeira_hora, valor_hora_adicional, valor_diaria, tolerancia_minutos) VALUES (?, ?, ?, ?, ?, ?)",
            tarifas
        )

    conn.commit()
    conn.close()

def calcular_valor(minutos, tipo_veiculo):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT valor_primeira_hora, valor_hora_adicional, tolerancia_minutos
        FROM tarifas WHERE tipo_veiculo = ? AND ativo = 1 LIMIT 1
    """, (tipo_veiculo,))
    tarifa = cursor.fetchone()
    conn.close()

    if not tarifa:
        return 0.0

    if minutos <= tarifa['tolerancia_minutos']:
        return 0.0

    horas = (minutos - tarifa['tolerancia_minutos'] + 59) // 60
    if horas <= 1:
        return tarifa['valor_primeira_hora']
    return tarifa['valor_primeira_hora'] + ((horas - 1) * tarifa['valor_hora_adicional'])

# =============================================
# TEMPLATE BASE (HTML)
# =============================================
BASE_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🅿️ Sistema de Estacionamento</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
    <style>
        :root {
            --primary: #0d6efd;
            --success: #198754;
            --warning: #ffc107;
            --danger: #dc3545;
        }
        body {
            background: #f0f2f5;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%) !important;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        .navbar-brand {
            font-weight: 700;
            font-size: 1.4rem;
        }
        .card {
            border: none;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            transition: transform 0.2s;
        }
        .card:hover {
            transform: translateY(-2px);
        }
        .stat-card {
            border-left: 4px solid;
        }
        .stat-card.livre { border-left-color: var(--success); }
        .stat-card.ocupada { border-left-color: var(--danger); }
        .stat-card.faturamento { border-left-color: var(--primary); }
        .stat-card.ativos { border-left-color: var(--warning); }
        .badge-livre { background: #d1e7dd; color: #0f5132; }
        .badge-ocupada { background: #f8d7da; color: #842029; }
        .badge-manutencao { background: #fff3cd; color: #664d03; }
        .badge-reservada { background: #cff4fc; color: #055160; }
        .vaga-card {
            text-align: center;
            padding: 1rem;
            border-radius: 10px;
            cursor: default;
        }
        .vaga-livre { background: #d1e7dd; border: 2px solid #198754; }
        .vaga-ocupada { background: #f8d7da; border: 2px solid #dc3545; }
        .vaga-manutencao { background: #fff3cd; border: 2px solid #ffc107; }
        .table th {
            background: #1a1a2e;
            color: white;
            font-weight: 500;
        }
        .btn-action {
            border-radius: 8px;
            font-weight: 500;
        }
        .form-control, .form-select {
            border-radius: 8px;
        }
        footer {
            margin-top: 3rem;
            padding: 1.5rem;
            background: #1a1a2e;
            color: #aaa;
            text-align: center;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark mb-4">
        <div class="container">
            <a class="navbar-brand" href="/">
                <i class="bi bi-p-square-fill"></i> Estacionamento
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="nav">
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item"><a class="nav-link" href="/"><i class="bi bi-house"></i> Dashboard</a></li>
                    <li class="nav-item"><a class="nav-link" href="/entrada"><i class="bi bi-box-arrow-in-right"></i> Entrada</a></li>
                    <li class="nav-item"><a class="nav-link" href="/saida"><i class="bi bi-box-arrow-right"></i> Saída</a></li>
                    <li class="nav-item"><a class="nav-link" href="/vagas"><i class="bi bi-grid"></i> Vagas</a></li>
                    <li class="nav-item"><a class="nav-link" href="/ativos"><i class="bi bi-car-front"></i> No Pátio</a></li>
                    <li class="nav-item"><a class="nav-link" href="/clientes"><i class="bi bi-people"></i> Clientes</a></li>
                    <li class="nav-item"><a class="nav-link" href="/relatorio"><i class="bi bi-graph-up"></i> Relatório</a></li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {{ content|safe }}
    </div>

    <footer>
        <div class="container">
            Sistema de Estacionamento &copy; 2026 &mdash; Banco de dados integrado (SQLite)
        </div>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

def render(content):
    return render_template_string(BASE_HTML, content=content)

# =============================================
# ROTAS
# =============================================
@app.route("/")
def dashboard():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM vagas WHERE status = 'livre'")
    livres = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM vagas WHERE status = 'ocupada'")
    ocupadas = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM estacionamentos WHERE status = 'ativo'")
    ativos = cursor.fetchone()[0]

    hoje = hoje_str()
    cursor.execute("""
        SELECT COALESCE(SUM(valor_total), 0) FROM estacionamentos
        WHERE status = 'finalizado' AND DATE(data_saida) = ?
    """, (hoje,))
    faturamento = cursor.fetchone()[0]

    cursor.execute("""
        SELECT e.id, v.numero, ve.placa, ve.modelo, e.data_entrada, c.nome AS dono
        FROM estacionamentos e
        JOIN vagas v ON e.vaga_id = v.id
        JOIN veiculos ve ON e.veiculo_id = ve.id
        LEFT JOIN clientes c ON e.cliente_id = c.id
        WHERE e.status = 'ativo'
        ORDER BY e.data_entrada DESC LIMIT 5
    """)
    recentes = cursor.fetchall()
    conn.close()

    rows = ""
    for r in recentes:
        dono = r['dono'] or 'Avulso'
        rows += f"""
        <tr>
            <td>{r['numero']}</td>
            <td><strong>{r['placa']}</strong></td>
            <td>{r['modelo'] or '-'}</td>
            <td>{dono}</td>
            <td>{formatar_data(r['data_entrada'])}</td>
        </tr>
        """

    if not rows:
        rows = '<tr><td colspan="5" class="text-center text-muted">Nenhum veículo no pátio</td></tr>'

    content = f"""
    <h2 class="mb-4"><i class="bi bi-speedometer2"></i> Dashboard</h2>
    <div class="row g-3 mb-4">
        <div class="col-md-3">
            <div class="card stat-card livre">
                <div class="card-body">
                    <h6 class="text-muted mb-1">Vagas Livres</h6>
                    <h2 class="mb-0 text-success">{livres}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card ocupada">
                <div class="card-body">
                    <h6 class="text-muted mb-1">Vagas Ocupadas</h6>
                    <h2 class="mb-0 text-danger">{ocupadas}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card ativos">
                <div class="card-body">
                    <h6 class="text-muted mb-1">Veículos no Pátio</h6>
                    <h2 class="mb-0 text-warning">{ativos}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card stat-card faturamento">
                <div class="card-body">
                    <h6 class="text-muted mb-1">Faturamento Hoje</h6>
                    <h2 class="mb-0 text-primary">R$ {faturamento:.2f}</h2>
                </div>
            </div>
        </div>
    </div>

    <div class="card">
        <div class="card-header bg-white">
            <strong><i class="bi bi-clock-history"></i> Últimas Entradas</strong>
        </div>
        <div class="card-body p-0">
            <table class="table table-hover mb-0">
                <thead>
                    <tr>
                        <th>Vaga</th>
                        <th>Placa</th>
                        <th>Modelo</th>
                        <th>Dono</th>
                        <th>Entrada</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render(content)

@app.route("/entrada", methods=["GET", "POST"])
def entrada():
    if request.method == "POST":
        placa_raw = request.form.get("placa", "").strip().upper()
        numero_vaga = request.form.get("vaga", "").strip().upper()
        modelo = request.form.get("modelo", "").strip() or None
        marca = request.form.get("marca", "").strip() or None
        cor = request.form.get("cor", "").strip() or None
        tipo = request.form.get("tipo", "carro")
        cliente_id = request.form.get("cliente_id", "").strip() or None

        ok_placa, placa_ou_msg = validar_placa(placa_raw)
        if not ok_placa:
            flash(placa_ou_msg, "danger")
            return redirect(url_for("entrada"))
        placa = placa_ou_msg

        if not numero_vaga:
            flash("Selecione uma vaga!", "danger")
            return redirect(url_for("entrada"))

        if cliente_id:
            try:
                cliente_id = int(cliente_id)
            except ValueError:
                cliente_id = None

        conn = conectar()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT id FROM vagas WHERE numero = ? AND status = 'livre'", (numero_vaga,))
            vaga = cursor.fetchone()
            if not vaga:
                flash("Vaga não disponível ou não existe!", "danger")
                return redirect(url_for("entrada"))

            cursor.execute("SELECT id FROM veiculos WHERE placa = ?", (placa,))
            veiculo = cursor.fetchone()

            if veiculo:
                veiculo_id = veiculo["id"]
            else:
                cursor.execute(
                    "INSERT INTO veiculos (placa, modelo, marca, cor, tipo, data_cadastro) VALUES (?, ?, ?, ?, ?, ?)",
                    (placa, modelo, marca, cor, tipo, agora_str())
                )
                veiculo_id = cursor.lastrowid

            # Se escolheu um dono, vincula veículo ao cliente (se ainda não estiver)
            if cliente_id:
                cursor.execute(
                    "SELECT id FROM cliente_veiculo WHERE cliente_id = ? AND veiculo_id = ?",
                    (cliente_id, veiculo_id)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO cliente_veiculo (cliente_id, veiculo_id) VALUES (?, ?)",
                        (cliente_id, veiculo_id)
                    )

            data_entrada = agora_str()
            cursor.execute(
                "INSERT INTO estacionamentos (vaga_id, veiculo_id, cliente_id, data_entrada, status) VALUES (?, ?, ?, ?, 'ativo')",
                (vaga["id"], veiculo_id, cliente_id, data_entrada)
            )
            cursor.execute("UPDATE vagas SET status = 'ocupada' WHERE id = ?", (vaga["id"],))
            conn.commit()

            dono_msg = ""
            if cliente_id:
                cursor.execute("SELECT nome FROM clientes WHERE id = ?", (cliente_id,))
                c = cursor.fetchone()
                if c:
                    dono_msg = f" — Dono: {c['nome']}"

            flash(f"Entrada registrada! Placa {placa} na vaga {numero_vaga}{dono_msg}", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Erro: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for("dashboard"))

    # GET - mostrar formulário
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT numero, setor, tipo FROM vagas WHERE status = 'livre' ORDER BY setor, numero")
    vagas_livres = cursor.fetchall()
    cursor.execute("SELECT id, nome, tipo FROM clientes ORDER BY nome")
    lista_clientes = cursor.fetchall()
    conn.close()

    options = ""
    for v in vagas_livres:
        options += f'<option value="{v["numero"]}">{v["numero"]} — Setor {v["setor"]} ({v["tipo"]})</option>'

    if not options:
        options = '<option disabled>Nenhuma vaga disponível</option>'

    clientes_options = '<option value="">— Sem dono cadastrado (avulso) —</option>'
    for c in lista_clientes:
        tipo_c = "Mensalista" if c["tipo"] == "mensalista" else "Avulso"
        clientes_options += f'<option value="{c["id"]}">{c["nome"]} ({tipo_c})</option>'

    content = f"""
    <h2 class="mb-4"><i class="bi bi-box-arrow-in-right"></i> Registrar Entrada</h2>
    <div class="row">
        <div class="col-md-8">
            <div class="card">
                <div class="card-body">
                    <form method="POST">
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label class="form-label">Placa *</label>
                                <input type="text" name="placa" id="placa_entrada" class="form-control form-control-lg" 
                                       placeholder="ABC1D23 ou ABC1234" required maxlength="8"
                                       style="text-transform: uppercase;"
                                       pattern="[A-Za-z]{{3}}[0-9][A-Za-z0-9][0-9]{{2}}|[A-Za-z]{{3}}[0-9]{{4}}"
                                       title="Formato Mercosul ABC1D23 ou antigo ABC1234">
                                <small class="text-muted">Mercosul: ABC1D23 · Antiga: ABC1234</small>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Vaga *</label>
                                <select name="vaga" class="form-select form-select-lg" required>
                                    <option value="">Selecione...</option>
                                    {options}
                                </select>
                            </div>
                            <div class="col-md-12">
                                <label class="form-label">Dono do veículo (cliente cadastrado)</label>
                                <select name="cliente_id" class="form-select form-select-lg">
                                    {clientes_options}
                                </select>
                                <small class="text-muted">Assim você saberá quem é o dono na hora da saída.</small>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Modelo</label>
                                <input type="text" name="modelo" class="form-control" placeholder="Civic">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Marca</label>
                                <input type="text" name="marca" class="form-control" placeholder="Honda">
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Cor</label>
                                <input type="text" name="cor" class="form-control" placeholder="Preto">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Tipo de Veículo</label>
                                <select name="tipo" class="form-select">
                                    <option value="carro">Carro</option>
                                    <option value="moto">Moto</option>
                                    <option value="suv">SUV</option>
                                    <option value="pcd">PCD</option>
                                </select>
                            </div>
                            <div class="col-12">
                                <button type="submit" class="btn btn-success btn-lg btn-action">
                                    <i class="bi bi-check-circle"></i> Registrar Entrada
                                </button>
                                <a href="/" class="btn btn-outline-secondary btn-lg btn-action">Cancelar</a>
                            </div>
                        </div>
                    </form>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card bg-light">
                <div class="card-body">
                    <h5><i class="bi bi-info-circle"></i> Dica</h5>
                    <p class="mb-0 text-muted">
                        Escolha o <strong>dono</strong> entre os clientes cadastrados.
                        Na saída e no pátio você verá o nome do proprietário.
                        Se não escolher, fica como avulso.
                    </p>
                </div>
            </div>
        </div>
    </div>
    <script>
        document.getElementById('placa_entrada')?.addEventListener('input', function(e) {{
            let v = e.target.value.replace(/[^A-Za-z0-9]/g, '').toUpperCase().slice(0, 7);
            e.target.value = v;
        }});
    </script>
    """
    return render(content)

@app.route("/saida", methods=["GET", "POST"])
def saida():
    if request.method == "POST":
        placa = request.form.get("placa", "").strip().upper()
        forma = request.form.get("forma_pagamento", "pix")
        valor_str = request.form.get("valor", "").strip()

        if not placa:
            flash("Placa é obrigatória!", "danger")
            return redirect(url_for("saida"))

        valor = formatar_valor(valor_str)
        if valor is None:
            flash("Informe um valor válido para cobrança (ex: 15.00)!", "danger")
            return redirect(url_for("saida"))

        conn = conectar()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT e.id, e.vaga_id, e.data_entrada, ve.tipo, ve.placa
                FROM estacionamentos e
                JOIN veiculos ve ON e.veiculo_id = ve.id
                WHERE ve.placa = ? AND e.status = 'ativo' LIMIT 1
            """, (placa,))
            reg = cursor.fetchone()

            if not reg:
                flash("Nenhum estacionamento ativo encontrado para esta placa!", "danger")
                return redirect(url_for("saida"))

            data_entrada = datetime.strptime(reg["data_entrada"], "%Y-%m-%d %H:%M:%S")
            data_saida = agora().replace(tzinfo=None)
            minutos = int((data_saida - data_entrada).total_seconds() / 60)

            data_saida_str = agora_str()
            cursor.execute("""
                UPDATE estacionamentos 
                SET data_saida = ?, valor_total = ?, forma_pagamento = ?, status = 'finalizado'
                WHERE id = ?
            """, (data_saida_str, valor, forma, reg["id"]))

            cursor.execute("UPDATE vagas SET status = 'livre' WHERE id = ?", (reg["vaga_id"],))
            conn.commit()

            flash(f"Saída registrada! Placa {placa} — Tempo: {minutos} min — Valor cobrado: R$ {valor:.2f}", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Erro: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for("dashboard"))

    # GET
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ve.placa, v.numero, ve.modelo, ve.tipo, e.data_entrada, c.nome AS dono
        FROM estacionamentos e
        JOIN vagas v ON e.vaga_id = v.id
        JOIN veiculos ve ON e.veiculo_id = ve.id
        LEFT JOIN clientes c ON e.cliente_id = c.id
        WHERE e.status = 'ativo'
        ORDER BY e.data_entrada
    """)
    ativos = cursor.fetchall()
    conn.close()

    options = ""
    for a in ativos:
        entrada = datetime.strptime(a["data_entrada"], "%Y-%m-%d %H:%M:%S")
        minutos = int((agora().replace(tzinfo=None) - entrada).total_seconds() / 60)
        sugerido = calcular_valor(minutos, a["tipo"])
        tempo = f"{minutos // 60}h{minutos % 60:02d}min" if minutos >= 60 else f"{minutos}min"
        dono = a["dono"] or "Avulso"
        options += f'<option value="{a["placa"]}" data-sugerido="{sugerido:.2f}">{a["placa"]} — {dono} — Vaga {a["numero"]} — {tempo} — R$ {sugerido:.2f}</option>'

    if not options:
        options = '<option disabled>Nenhum veículo no pátio</option>'

    content = f"""
    <h2 class="mb-4"><i class="bi bi-box-arrow-right"></i> Registrar Saída</h2>
    <div class="row">
        <div class="col-md-8">
            <div class="card">
                <div class="card-body">
                    <form method="POST">
                        <div class="row g-3">
                            <div class="col-md-12">
                                <label class="form-label">Veículo *</label>
                                <select name="placa" id="placa" class="form-select form-select-lg" required onchange="preencherValor()">
                                    <option value="">Selecione a placa...</option>
                                    {options}
                                </select>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Valor a cobrar (R$) *</label>
                                <div class="input-group input-group-lg">
                                    <span class="input-group-text">R$</span>
                                    <input type="text" name="valor" id="valor" class="form-control form-control-lg"
                                           placeholder="0,00" required inputmode="decimal"
                                           autocomplete="off">
                                </div>
                                <small class="text-muted">Digite os números — formata automaticamente (ex: 1500 → 15,00)</small>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Forma de pagamento</label>
                                <select name="forma_pagamento" class="form-select form-select-lg">
                                    <option value="pix">PIX</option>
                                    <option value="dinheiro">Dinheiro</option>
                                    <option value="cartao_credito">Cartão Crédito</option>
                                    <option value="cartao_debito">Cartão Débito</option>
                                    <option value="mensalidade">Mensalidade</option>
                                </select>
                            </div>
                            <div class="col-12">
                                <button type="submit" class="btn btn-danger btn-lg btn-action">
                                    <i class="bi bi-check-circle"></i> Registrar Saída e Cobrar
                                </button>
                                <a href="/" class="btn btn-outline-secondary btn-lg btn-action">Cancelar</a>
                            </div>
                        </div>
                    </form>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card bg-light">
                <div class="card-body">
                    <h5><i class="bi bi-info-circle"></i> Como funciona</h5>
                    <p class="mb-0 text-muted">
                        Ao selecionar o veículo, o sistema sugere um valor com base no tempo.
                        Você pode <strong>alterar esse valor</strong> para o que o cliente vai pagar.
                        O valor informado entra no <strong>Faturamento de Hoje</strong>.
                    </p>
                </div>
            </div>
        </div>
    </div>
    <script>
        function formatarMoeda(input) {{
            let digits = input.value.replace(/\\D/g, '');
            if (digits === '') {{ input.value = ''; return; }}
            let num = (parseInt(digits, 10) / 100).toFixed(2);
            input.value = num.replace('.', ',');
        }}
        function preencherValor() {{
            const select = document.getElementById('placa');
            const option = select.options[select.selectedIndex];
            const sugerido = option.getAttribute('data-sugerido');
            if (sugerido !== null && sugerido !== '') {{
                const el = document.getElementById('valor');
                el.value = parseFloat(sugerido).toFixed(2).replace('.', ',');
            }}
        }}
        document.getElementById('valor')?.addEventListener('input', function() {{
            formatarMoeda(this);
        }});
        document.getElementById('valor')?.addEventListener('blur', function() {{
            if (this.value) {{
                let n = parseFloat(this.value.replace(',', '.'));
                if (!isNaN(n)) this.value = n.toFixed(2).replace('.', ',');
            }}
        }});
    </script>
    """
    return render(content)

@app.route("/vagas")
def vagas():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vagas ORDER BY setor, numero")
    todas = cursor.fetchall()
    conn.close()

    cards = ""
    for v in todas:
        css = f"vaga-{v['status']}"
        icon = "bi-check-circle" if v['status'] == 'livre' else "bi-x-circle"
        cards += f"""
        <div class="col-6 col-md-3 col-lg-2">
            <div class="vaga-card {css}">
                <i class="bi {icon} fs-4"></i>
                <h5 class="mb-0 mt-1">{v['numero']}</h5>
                <small>{v['setor']} · {v['tipo']}</small><br>
                <small class="text-muted">R$ {v['valor_hora']:.2f}/h</small>
            </div>
        </div>
        """

    content = f"""
    <h2 class="mb-4"><i class="bi bi-grid"></i> Mapa de Vagas</h2>
    <div class="d-flex gap-3 mb-3">
        <span class="badge badge-livre px-3 py-2">Livre</span>
        <span class="badge badge-ocupada px-3 py-2">Ocupada</span>
        <span class="badge badge-manutencao px-3 py-2">Manutenção</span>
        <span class="badge badge-reservada px-3 py-2">Reservada</span>
    </div>
    <div class="row g-3">
        {cards}
    </div>
    """
    return render(content)

@app.route("/ativos")
def ativos():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.id, v.numero, v.setor, ve.placa, ve.modelo, ve.cor, ve.tipo, e.data_entrada,
               c.nome AS dono
        FROM estacionamentos e
        JOIN vagas v ON e.vaga_id = v.id
        JOIN veiculos ve ON e.veiculo_id = ve.id
        LEFT JOIN clientes c ON e.cliente_id = c.id
        WHERE e.status = 'ativo'
        ORDER BY e.data_entrada
    """)
    lista = cursor.fetchall()
    conn.close()

    rows = ""
    for r in lista:
        entrada = datetime.strptime(r["data_entrada"], "%Y-%m-%d %H:%M:%S")
        minutos = int((agora().replace(tzinfo=None) - entrada).total_seconds() / 60)
        horas = minutos // 60
        mins = minutos % 60
        tempo = f"{horas}h {mins}min" if horas else f"{mins}min"
        dono = r["dono"] or '<span class="text-muted">Avulso</span>'

        rows += f"""
        <tr>
            <td><strong>{r['numero']}</strong></td>
            <td>{r['setor']}</td>
            <td><span class="badge bg-dark">{r['placa']}</span></td>
            <td>{r['modelo'] or '-'}</td>
            <td>{r['cor'] or '-'}</td>
            <td>{r['tipo']}</td>
            <td>{dono}</td>
            <td>{formatar_data(r['data_entrada'])}</td>
            <td>{tempo}</td>
        </tr>
        """

    if not rows:
        rows = '<tr><td colspan="9" class="text-center text-muted py-4">Nenhum veículo no pátio no momento</td></tr>'

    content = f"""
    <h2 class="mb-4"><i class="bi bi-car-front"></i> Veículos no Pátio</h2>
    <div class="card">
        <div class="card-body p-0">
            <table class="table table-hover mb-0">
                <thead>
                    <tr>
                        <th>Vaga</th>
                        <th>Setor</th>
                        <th>Placa</th>
                        <th>Modelo</th>
                        <th>Cor</th>
                        <th>Tipo</th>
                        <th>Dono</th>
                        <th>Entrada</th>
                        <th>Tempo</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render(content)

@app.route("/relatorio")
def relatorio():
    conn = conectar()
    cursor = conn.cursor()
    hoje = hoje_str()

    cursor.execute("""
        SELECT COUNT(*) AS total, COALESCE(SUM(valor_total), 0) AS fatura, COALESCE(AVG(valor_total), 0) AS media
        FROM estacionamentos
        WHERE status = 'finalizado' AND DATE(data_saida) = ?
    """, (hoje,))
    dia = cursor.fetchone()

    cursor.execute("""
        SELECT ve.placa, v.numero, e.data_entrada, e.data_saida, e.valor_total, e.forma_pagamento
        FROM estacionamentos e
        JOIN veiculos ve ON e.veiculo_id = ve.id
        JOIN vagas v ON e.vaga_id = v.id
        WHERE e.status = 'finalizado' AND DATE(e.data_saida) = ?
        ORDER BY e.data_saida DESC
    """, (hoje,))
    movimentacoes = cursor.fetchall()
    conn.close()

    rows = ""
    for m in movimentacoes:
        rows += f"""
        <tr>
            <td>{m['placa']}</td>
            <td>{m['numero']}</td>
            <td>{formatar_data(m['data_entrada'])}</td>
            <td>{formatar_data(m['data_saida'])}</td>
            <td>R$ {m['valor_total']:.2f}</td>
            <td>{m['forma_pagamento'] or '-'}</td>
        </tr>
        """

    if not rows:
        rows = '<tr><td colspan="6" class="text-center text-muted py-4">Nenhuma movimentação hoje</td></tr>'

    content = f"""
    <h2 class="mb-4"><i class="bi bi-graph-up"></i> Relatório do Dia — {formatar_data(hoje)}</h2>
    <div class="row g-3 mb-4">
        <div class="col-md-4">
            <div class="card stat-card livres">
                <div class="card-body text-center">
                    <h6 class="text-muted">Veículos Atendidos</h6>
                    <h2>{dia['total']}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card stat-card faturamento">
                <div class="card-body text-center">
                    <h6 class="text-muted">Faturamento</h6>
                    <h2 class="text-primary">R$ {dia['fatura']:.2f}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card stat-card ativos">
                <div class="card-body text-center">
                    <h6 class="text-muted">Ticket Médio</h6>
                    <h2>R$ {dia['media']:.2f}</h2>
                </div>
            </div>
        </div>
    </div>

    <div class="card">
        <div class="card-header bg-white">
            <strong>Movimentações de Hoje</strong>
        </div>
        <div class="card-body p-0">
            <table class="table table-hover mb-0">
                <thead>
                    <tr>
                        <th>Placa</th>
                        <th>Vaga</th>
                        <th>Entrada</th>
                        <th>Saída</th>
                        <th>Valor</th>
                        <th>Pagamento</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render(content)

# =============================================
# CLIENTES
# =============================================
@app.route("/clientes")
def clientes():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.*, 
               (SELECT COUNT(*) FROM cliente_veiculo cv WHERE cv.cliente_id = c.id) AS total_veiculos
        FROM clientes c
        ORDER BY c.nome
    """)
    lista = cursor.fetchall()
    conn.close()

    rows = ""
    for c in lista:
        tipo_badge = '<span class="badge bg-primary">Mensalista</span>' if c['tipo'] == 'mensalista' else '<span class="badge bg-secondary">Avulso</span>'
        rows += f"""
        <tr>
            <td>{c['id']}</td>
            <td><strong>{c['nome']}</strong></td>
            <td>{c['cpf'] or '-'}</td>
            <td>{c['telefone'] or '-'}</td>
            <td>{c['email'] or '-'}</td>
            <td>{tipo_badge}</td>
            <td>{c['total_veiculos']}</td>
            <td>
                <a href="/cliente/{c['id']}" class="btn btn-sm btn-outline-primary">Ver</a>
                <form method="POST" action="/cliente/{c['id']}/remover" style="display:inline" onsubmit="return confirm('Tem certeza que deseja remover o cliente {c['nome']}?')">
                    <button type="submit" class="btn btn-sm btn-outline-danger">Remover</button>
                </form>
            </td>
        </tr>
        """
    if not rows:
        rows = '<tr><td colspan="8" class="text-center text-muted py-4">Nenhum cliente cadastrado</td></tr>'

    content = f"""
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="mb-0"><i class="bi bi-people"></i> Clientes</h2>
        <a href="/clientes/novo" class="btn btn-success"><i class="bi bi-plus-circle"></i> Novo Cliente</a>
    </div>
    <div class="card">
        <div class="card-body p-0">
            <table class="table table-hover mb-0">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Nome</th>
                        <th>CPF</th>
                        <th>Telefone</th>
                        <th>E-mail</th>
                        <th>Tipo</th>
                        <th>Veículos</th>
                        <th>Ações</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render(content)

@app.route("/clientes/novo", methods=["GET", "POST"])
def cliente_novo():
    if request.method == "POST":
        nome_raw = request.form.get("nome", "").strip()
        cpf_raw = request.form.get("cpf", "").strip() or None
        telefone = request.form.get("telefone", "").strip() or None
        email = request.form.get("email", "").strip() or None
        tipo = request.form.get("tipo", "avulso")

        ok_nome, nome_ou_msg = validar_nome(nome_raw)
        if not ok_nome:
            flash(nome_ou_msg, "danger")
            return redirect(url_for("cliente_novo"))
        nome = nome_ou_msg

        ok_cpf, cpf_ou_msg = validar_cpf(cpf_raw)
        if not ok_cpf:
            flash(cpf_ou_msg, "danger")
            return redirect(url_for("cliente_novo"))
        cpf = cpf_ou_msg

        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("E-mail inválido.", "danger")
            return redirect(url_for("cliente_novo"))

        if telefone:
            tel_nums = re.sub(r'\D', '', telefone)
            if len(tel_nums) < 10 or len(tel_nums) > 11:
                flash("Telefone inválido. Use DDD + número (10 ou 11 dígitos).", "danger")
                return redirect(url_for("cliente_novo"))
            if len(tel_nums) == 11:
                telefone = f"({tel_nums[:2]}) {tel_nums[2:7]}-{tel_nums[7:]}"
            else:
                telefone = f"({tel_nums[:2]}) {tel_nums[2:6]}-{tel_nums[6:]}"

        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO clientes (nome, cpf, telefone, email, tipo, data_cadastro) VALUES (?, ?, ?, ?, ?, ?)",
                (nome, cpf, telefone, email, tipo, agora_str())
            )
            conn.commit()
            flash(f"Cliente '{nome}' cadastrado com sucesso!", "success")
            return redirect(url_for("clientes"))
        except sqlite3.IntegrityError:
            flash("Já existe um cliente com este CPF!", "danger")
        except Exception as e:
            flash(f"Erro: {e}", "danger")
        finally:
            conn.close()
        return redirect(url_for("cliente_novo"))

    content = """
    <h2 class="mb-4"><i class="bi bi-person-plus"></i> Novo Cliente</h2>
    <div class="card">
        <div class="card-body">
            <form method="POST" id="formCliente">
                <div class="row g-3">
                    <div class="col-md-6">
                        <label class="form-label">Nome completo *</label>
                        <input type="text" name="nome" id="nome" class="form-control form-control-lg"
                               required placeholder="Ex: João da Silva" minlength="3">
                        <small class="text-muted">Nome e sobrenome, apenas letras</small>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">CPF</label>
                        <input type="text" name="cpf" id="cpf" class="form-control form-control-lg"
                               placeholder="000.000.000-00" maxlength="14">
                        <small class="text-muted">Validado com dígitos verificadores</small>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label">Telefone</label>
                        <input type="text" name="telefone" id="telefone" class="form-control"
                               placeholder="(11) 99999-8888" maxlength="15">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label">E-mail</label>
                        <input type="email" name="email" class="form-control" placeholder="email@exemplo.com">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label">Tipo</label>
                        <select name="tipo" class="form-select">
                            <option value="avulso">Avulso</option>
                            <option value="mensalista">Mensalista</option>
                        </select>
                    </div>
                    <div class="col-12">
                        <button type="submit" class="btn btn-success btn-lg">Salvar Cliente</button>
                        <a href="/clientes" class="btn btn-outline-secondary btn-lg">Cancelar</a>
                    </div>
                </div>
            </form>
        </div>
    </div>
    <script>
        // Máscara CPF
        document.getElementById('cpf')?.addEventListener('input', function(e) {
            let v = e.target.value.replace(/\\D/g, '').slice(0, 11);
            if (v.length > 9) v = v.replace(/(\\d{3})(\\d{3})(\\d{3})(\\d{1,2})/, '$1.$2.$3-$4');
            else if (v.length > 6) v = v.replace(/(\\d{3})(\\d{3})(\\d{1,3})/, '$1.$2.$3');
            else if (v.length > 3) v = v.replace(/(\\d{3})(\\d{1,3})/, '$1.$2');
            e.target.value = v;
        });
        // Máscara telefone
        document.getElementById('telefone')?.addEventListener('input', function(e) {
            let v = e.target.value.replace(/\\D/g, '').slice(0, 11);
            if (v.length > 6) v = v.replace(/(\\d{2})(\\d{5})(\\d{0,4})/, '($1) $2-$3');
            else if (v.length > 2) v = v.replace(/(\\d{2})(\\d{0,5})/, '($1) $2');
            else if (v.length > 0) v = v.replace(/(\\d{0,2})/, '($1');
            e.target.value = v;
        });
        // Nome: só letras e espaços
        document.getElementById('nome')?.addEventListener('input', function(e) {
            e.target.value = e.target.value.replace(/[^A-Za-zÀ-ÿ\\s'.\\-]/g, '');
        });
    </script>
    """
    return render(content)

@app.route("/cliente/<int:cliente_id>")
def cliente_detalhe(cliente_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
    cliente = cursor.fetchone()
    if not cliente:
        flash("Cliente não encontrado!", "danger")
        return redirect(url_for("clientes"))

    # Veículos vinculados
    cursor.execute("""
        SELECT v.* FROM veiculos v
        JOIN cliente_veiculo cv ON cv.veiculo_id = v.id
        WHERE cv.cliente_id = ?
        ORDER BY v.placa
    """, (cliente_id,))
    veiculos = cursor.fetchall()

    # Todos os veículos (para vincular)
    cursor.execute("SELECT id, placa, modelo FROM veiculos ORDER BY placa")
    todos_veiculos = cursor.fetchall()
    conn.close()

    veiculos_rows = ""
    for v in veiculos:
        veiculos_rows += f"""
        <tr>
            <td><strong>{v['placa']}</strong></td>
            <td>{v['modelo'] or '-'}</td>
            <td>{v['marca'] or '-'}</td>
            <td>{v['cor'] or '-'}</td>
            <td>{v['tipo']}</td>
            <td>
                <form method="POST" action="/cliente/{cliente_id}/desvincular" style="display:inline">
                    <input type="hidden" name="veiculo_id" value="{v['id']}">
                    <button type="submit" class="btn btn-sm btn-outline-danger" onclick="return confirm('Desvincular este veículo?')">Remover</button>
                </form>
            </td>
        </tr>
        """
    if not veiculos_rows:
        veiculos_rows = '<tr><td colspan="6" class="text-center text-muted">Nenhum veículo vinculado</td></tr>'

    options = "".join([f'<option value="{v["id"]}">{v["placa"]} — {v["modelo"] or "s/ modelo"}</option>' for v in todos_veiculos])

    tipo_badge = '<span class="badge bg-primary">Mensalista</span>' if cliente['tipo'] == 'mensalista' else '<span class="badge bg-secondary">Avulso</span>'

    content = f"""
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="mb-0"><i class="bi bi-person"></i> {cliente['nome']}</h2>
        <a href="/clientes" class="btn btn-outline-secondary">Voltar</a>
    </div>

    <div class="row g-3 mb-4">
        <div class="col-md-6">
            <div class="card">
                <div class="card-header bg-white"><strong>Dados do Cliente</strong></div>
                <div class="card-body">
                    <p><strong>CPF:</strong> {cliente['cpf'] or '-'}</p>
                    <p><strong>Telefone:</strong> {cliente['telefone'] or '-'}</p>
                    <p><strong>E-mail:</strong> {cliente['email'] or '-'}</p>
                    <p><strong>Tipo:</strong> {tipo_badge}</p>
                    <p class="mb-0"><strong>Cadastro:</strong> {formatar_data(cliente['data_cadastro'])}</p>
                </div>
            </div>
        </div>
        <div class="col-md-6">
            <div class="card">
                <div class="card-header bg-white"><strong>Vincular Veículo</strong></div>
                <div class="card-body">
                    <form method="POST" action="/cliente/{cliente_id}/vincular">
                        <div class="input-group">
                            <select name="veiculo_id" class="form-select" required>
                                <option value="">Selecione o veículo...</option>
                                {options}
                            </select>
                            <button type="submit" class="btn btn-primary">Vincular</button>
                        </div>
                    </form>
                    <small class="text-muted mt-2 d-block">O veículo precisa estar cadastrado no sistema (através de uma entrada).</small>
                </div>
            </div>
        </div>
    </div>

    <div class="card">
        <div class="card-header bg-white"><strong>Veículos Vinculados (cliente_veiculo)</strong></div>
        <div class="card-body p-0">
            <table class="table table-hover mb-0">
                <thead>
                    <tr>
                        <th>Placa</th>
                        <th>Modelo</th>
                        <th>Marca</th>
                        <th>Cor</th>
                        <th>Tipo</th>
                        <th>Ação</th>
                    </tr>
                </thead>
                <tbody>
                    {veiculos_rows}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render(content)

@app.route("/cliente/<int:cliente_id>/vincular", methods=["POST"])
def cliente_vincular(cliente_id):
    veiculo_id = request.form.get("veiculo_id")
    if not veiculo_id:
        flash("Selecione um veículo!", "danger")
        return redirect(url_for("cliente_detalhe", cliente_id=cliente_id))

    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO cliente_veiculo (cliente_id, veiculo_id) VALUES (?, ?)",
            (cliente_id, veiculo_id)
        )
        conn.commit()
        flash("Veículo vinculado com sucesso!", "success")
    except sqlite3.IntegrityError:
        flash("Este veículo já está vinculado a este cliente!", "warning")
    except Exception as e:
        flash(f"Erro: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("cliente_detalhe", cliente_id=cliente_id))

@app.route("/cliente/<int:cliente_id>/desvincular", methods=["POST"])
def cliente_desvincular(cliente_id):
    veiculo_id = request.form.get("veiculo_id")
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM cliente_veiculo WHERE cliente_id = ? AND veiculo_id = ?",
            (cliente_id, veiculo_id)
        )
        conn.commit()
        flash("Veículo desvinculado!", "success")
    except Exception as e:
        flash(f"Erro: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("cliente_detalhe", cliente_id=cliente_id))

@app.route("/cliente/<int:cliente_id>/remover", methods=["POST"])
def cliente_remover(cliente_id):
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT nome FROM clientes WHERE id = ?", (cliente_id,))
        cliente = cursor.fetchone()
        if not cliente:
            flash("Cliente não encontrado!", "danger")
            return redirect(url_for("clientes"))

        # Remove vínculos com veículos primeiro
        cursor.execute("DELETE FROM cliente_veiculo WHERE cliente_id = ?", (cliente_id,))
        # Remove o cliente
        cursor.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
        conn.commit()
        flash(f"Cliente '{cliente['nome']}' removido com sucesso!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Erro ao remover cliente: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("clientes"))

# =============================================
# INICIALIZAÇÃO
# =============================================
if __name__ == "__main__":
    print("Inicializando banco de dados...")
    inicializar_banco()
    print(f"Banco: {DB_PATH}")
    print("\n🚀 Servidor iniciado!")
    print("   Acesse: http://127.0.0.1:5000")
    print("   Pressione CTRL+C para parar\n")
    app.run(debug=True, host="127.0.0.1", port=5000)
