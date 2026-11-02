# ============================================================
# RegulaRotulo — Tkinter + FastAPI + Docling + Tesseract
# OCR principal: Docling
# OCR alternativo: Tesseract
# Busca de arquivos: binária (nome exato) + sequencial (trecho)
# ============================================================

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# -------------------- DEPENDÊNCIAS OPCIONAIS --------------------
DOCLING_OK = False
DocumentConverter = None
InputFormat = PdfFormatOption = PdfPipelineOptions = None

try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    DOCLING_OK = True
except ImportError:
    pass

TESSERACT_OK = False
pytesseract = None
Image = ImageOps = ImageFilter = ImageEnhance = None

try:
    from PIL import Image, ImageOps, ImageFilter, ImageEnhance
except ImportError:
    pass

try:
    import pytesseract as _pt
    pytesseract = _pt
    TESSERACT_OK = True
    caminho_win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(caminho_win):
        pytesseract.pytesseract.tesseract_cmd = caminho_win
except ImportError:
    pass

# -------------------- CONFIGURAÇÕES --------------------
AZUL_MARINHO = "#0A2540"
AZUL_ESCURO = "#061828"
AMARELO = "#F0B429"
AMARELO_ESCURO = "#D4A017"
BRANCO = "#FFFFFF"
PRETO = "#111111"
CINZA = "#6B7280"
CINZA_CLARO = "#F3F4F6"
VERDE = "#22C55E"
VERMELHO = "#EF4444"

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "rotulocreci_data.json"
PASTA_ARQUIVOS = BASE_DIR / "arquivos_rotulos"
API_URL = "http://127.0.0.1:8000"

EXTENSOES_SUPORTADAS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"
}

# O conversor é criado uma vez para evitar recarregar os modelos a cada imagem.
DOCLING_CONVERTER = None
DOCLING_LOCK = threading.Lock()


def criar_conversor_docling():
    """Cria conversor Docling com OCR habilitado para PDFs."""
    global DOCLING_CONVERTER

    if not DOCLING_OK:
        return None

    if DOCLING_CONVERTER is not None:
        return DOCLING_CONVERTER

    with DOCLING_LOCK:
        if DOCLING_CONVERTER is None:
            try:
                opcoes_pdf = PdfPipelineOptions()
                opcoes_pdf.do_ocr = True
                opcoes_pdf.do_table_structure = True

                DOCLING_CONVERTER = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(
                            pipeline_options=opcoes_pdf
                        )
                    }
                )
            except Exception as erro:
                print(f"Não foi possível iniciar o Docling: {erro}")
                return None

    return DOCLING_CONVERTER


def carregar_dados():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)
                if isinstance(dados, dict):
                    dados.setdefault("projetos", [])
                    return dados
        except (json.JSONDecodeError, OSError) as erro:
            print(f"Erro ao carregar dados: {erro}")
    return {"projetos": []}


def salvar_dados(dados):
    with open(DATA_FILE, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)


# ============================================================
# BUSCA DE ARQUIVOS
# ============================================================
def busca_sequencial(lista, termo, chave=None):
    """
    Busca sequencial O(n).
    Procura um trecho do nome/campo em todos os itens.
    """
    termo = (termo or "").strip().casefold()
    if not termo:
        return list(lista)

    encontrados = []
    for item in lista:
        if isinstance(item, dict):
            texto = str(item.get(chave, "")) if chave else str(item.get("nome", ""))
        else:
            texto = str(item)

        if termo in texto.casefold():
            encontrados.append(item)

    return encontrados


def busca_binaria_por_nome(arquivos, nome_exato):
    """
    Busca binária O(log n) por nome exato.
    A lista precisa estar ordenada pelo nome, sem diferenciar maiúsculas.
    """
    alvo = (nome_exato or "").strip().casefold()
    if not alvo:
        return None

    ordenados = sorted(arquivos, key=lambda item: item.name.casefold())
    esquerda, direita = 0, len(ordenados) - 1

    while esquerda <= direita:
        meio = (esquerda + direita) // 2
        nome_meio = ordenados[meio].name.casefold()

        if nome_meio == alvo:
            return ordenados[meio]
        if nome_meio < alvo:
            esquerda = meio + 1
        else:
            direita = meio - 1

    return None


def indexar_arquivos(pasta):
    """Indexa recursivamente imagens e PDFs de uma pasta."""
    raiz = Path(pasta)
    if not raiz.exists() or not raiz.is_dir():
        return []

    arquivos = []
    try:
        for caminho in raiz.rglob("*"):
            if caminho.is_file() and caminho.suffix.casefold() in EXTENSOES_SUPORTADAS:
                arquivos.append(caminho)
    except OSError as erro:
        print(f"Erro ao indexar arquivos: {erro}")

    return sorted(arquivos, key=lambda item: item.name.casefold())


def procurar_arquivo(arquivos, termo):
    """
    Primeiro tenta nome exato com busca binária.
    Se não encontrar, procura trechos com busca sequencial.
    """
    termo = (termo or "").strip()
    if not termo:
        return list(arquivos)

    exato = busca_binaria_por_nome(arquivos, termo)
    if exato is not None:
        return [exato]

    return busca_sequencial(arquivos, termo, chave=None)


def arquivo_ja_selecionado(caminhos, caminho_novo):
    nome = Path(caminho_novo).name.casefold()
    return any(c and Path(c).name.casefold() == nome for c in caminhos)


# ============================================================
# OCR: DOCLING PRIMEIRO, TESSERACT COMO ALTERNATIVA
# ============================================================
def extrair_com_docling(caminho):
    if not DOCLING_OK:
        return ""

    try:
        conversor = criar_conversor_docling()
        if conversor is None:
            return ""

        resultado = conversor.convert(str(caminho))
        documento = resultado.document
        texto = documento.export_to_markdown()
        return (texto or "").strip().lower()
    except Exception as erro:
        print(f"Docling: {erro}")
        return ""


def extrair_com_tesseract(caminho):
    if not TESSERACT_OK or pytesseract is None or Image is None:
        return ""

    # Tesseract/Pillow não leem PDF diretamente; Docling é usado para PDF.
    if Path(caminho).suffix.casefold() == ".pdf":
        return ""

    try:
        imagem = Image.open(caminho)
        if imagem.mode != "RGB":
            imagem = imagem.convert("RGB")

        largura, altura = imagem.size
        if largura and largura < 1400:
            escala = 1400 / largura
            imagem = imagem.resize(
                (int(largura * escala), int(altura * escala)),
                Image.Resampling.LANCZOS
            )

        imagem = ImageOps.grayscale(imagem)
        imagem = ImageEnhance.Contrast(imagem).enhance(1.8)
        imagem = imagem.filter(ImageFilter.SHARPEN)

        try:
            return pytesseract.image_to_string(imagem, lang="por+eng").lower()
        except Exception:
            return pytesseract.image_to_string(imagem, lang="eng").lower()

    except Exception as erro:
        print(f"Tesseract: {erro}")
        return ""


def extrair_texto(caminho):
    if not caminho:
        return "", "nenhum"

    texto = extrair_com_docling(caminho)
    if texto and len(texto.strip()) > 5:
        return texto, "docling"

    texto = extrair_com_tesseract(caminho)
    if texto and len(texto.strip()) > 5:
        return texto, "tesseract"

    return "", "nenhum"


def contem_algum(texto, termos):
    texto = (texto or "").casefold()
    return any(termo.casefold() in texto for termo in termos)


def analisar_rotulo(fotos, nome_produto=""):
    textos = {}
    motores = []
    texto_geral = ""

    for face, caminho in fotos.items():
        texto, motor = extrair_texto(caminho)
        textos[face] = texto
        texto_geral += " " + texto
        if motor != "nenhum":
            motores.append(motor)

    nao_conformidades = []
    fotos_ok = sum(1 for caminho in fotos.values() if caminho)

    if fotos_ok < 2:
        nao_conformidades.append(
            "Imagens insuficientes. Envie Painel Principal e Tabela Nutricional. "
            "(RDC 429/2020)"
        )

    if not fotos.get("nutricional"):
        nao_conformidades.append(
            "Tabela Nutricional não enviada. (RDC 429/2020 e IN 75/2020)"
        )
    else:
        texto = textos.get("nutricional", "")
        if not contem_algum(texto, [
            "porção", "porcao", "porções", "porcoes",
            "informação nutricional", "informacao nutricional"
        ]):
            nao_conformidades.append(
                "Não foi possível identificar a porção. (IN 75/2020)"
            )

        if not contem_algum(texto, [
            "valor energético", "valor energetico", "kcal", "kj",
            "caloria", "energia"
        ]):
            nao_conformidades.append(
                "Valor energético (kcal/kJ) não identificado. (RDC 429/2020)"
            )

    if not fotos.get("ingredientes"):
        nao_conformidades.append(
            "Lista de ingredientes e alergênicos não verificada. "
            "(RDC 26/2015 e RDC 727/2022)"
        )
    else:
        texto = textos.get("ingredientes", "")
        if not contem_algum(texto, ["ingrediente", "ingredientes"]):
            nao_conformidades.append(
                "Palavra 'Ingredientes' não identificada. (RDC 727/2022)"
            )

        if not contem_algum(texto, [
            "contém", "contem", "alergên", "alergen", "glúten",
            "gluten", "não contém", "nao contem", "traços", "tracos"
        ]):
            nao_conformidades.append(
                "Declaração de alergênicos não identificada. (RDC 26/2015)"
            )

    if fotos.get("principal"):
        texto = textos.get("principal", "")
        if not contem_algum(texto, [
            "peso", "conteúdo", "conteudo", "líquido", "liquido",
            "500g", "500 g", " g", "ml", "kg"
        ]):
            nao_conformidades.append(
                "Peso/conteúdo líquido não identificado com segurança. "
                "(RDC 727/2022)"
            )

    if fotos_ok >= 1 and len(texto_geral.strip()) < 15:
        nao_conformidades.append(
            "Pouco texto reconhecido. Verifique nitidez, iluminação e enquadramento."
        )

    quantidade = len(nao_conformidades)
    baixo = min(10 + quantidade * 8, 40)
    medio = min(25 + quantidade * 6, 55)
    alto = max(100 - baixo - medio, 35)

    motor = "docling" if "docling" in motores else (
        "tesseract" if "tesseract" in motores else "nenhum"
    )

    return {
        "produto": nome_produto,
        "ncs": nao_conformidades,
        "nao_conformidades": nao_conformidades,
        "scores": {"alto": alto, "medio": medio, "baixo": baixo},
        "textos": textos,
        "ocr_ativo": motor != "nenhum",
        "motor": motor,
        "pendencias": quantidade,
        "status": (
            "conforme" if quantidade <= 1
            else "analise" if quantidade <= 2
            else "pendencias"
        )
    }


# ============================================================
# API FASTAPI
# ============================================================
API_OK = False
api = None

try:
    from fastapi import FastAPI, File, UploadFile, Form
    from fastapi.middleware.cors import CORSMiddleware

    api = FastAPI(title="RegulaRotulo API", version="2.0.0")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"]
    )

    @api.get("/")
    def raiz():
        return {
            "app": "RegulaRotulo API",
            "status": "online",
            "docling": DOCLING_OK,
            "tesseract": TESSERACT_OK
        }

    @api.get("/health")
    def health():
        return {"ok": True}

    @api.post("/analisar")
    async def api_analisar(
        nome_produto: str = Form("Produto"),
        principal: Optional[UploadFile] = File(None),
        nutricional: Optional[UploadFile] = File(None),
        ingredientes: Optional[UploadFile] = File(None),
        outros: Optional[UploadFile] = File(None)
    ):
        faces = {
            "principal": principal,
            "nutricional": nutricional,
            "ingredientes": ingredientes,
            "outros": outros
        }
        caminhos = {}
        temporarios = []

        try:
            for face, arquivo in faces.items():
                if arquivo is None:
                    caminhos[face] = None
                    continue

                extensao = Path(arquivo.filename or "imagem.jpg").suffix or ".jpg"
                temporario = tempfile.NamedTemporaryFile(
                    delete=False, suffix=extensao
                )
                conteudo = await arquivo.read()
                temporario.write(conteudo)
                temporario.close()

                caminhos[face] = temporario.name
                temporarios.append(temporario.name)

            return analisar_rotulo(caminhos, nome_produto)

        finally:
            for caminho in temporarios:
                try:
                    os.unlink(caminho)
                except OSError:
                    pass

    API_OK = True

except ImportError:
    API_OK = False
    api = None


def iniciar_api_background():
    if not API_OK or api is None:
        print("API indisponível. Instale FastAPI, Uvicorn e python-multipart.")
        return

    try:
        import uvicorn

        def executar():
            uvicorn.run(
                api,
                host="127.0.0.1",
                port=8000,
                log_level="warning"
            )

        threading.Thread(target=executar, daemon=True).start()
        print(f"API disponível em {API_URL}/docs")

    except Exception as erro:
        print(f"Erro ao iniciar API: {erro}")


def analisar_via_api(fotos, nome_produto):
    try:
        import requests
    except ImportError:
        resultado = analisar_rotulo(fotos, nome_produto)
        resultado["via_api"] = False
        return resultado

    arquivos = {}
    handles = []

    try:
        for face, caminho in fotos.items():
            if caminho and os.path.exists(caminho):
                handle = open(caminho, "rb")
                handles.append(handle)
                mime = "application/pdf" if Path(caminho).suffix.casefold() == ".pdf" else "image/jpeg"
                arquivos[face] = (os.path.basename(caminho), handle, mime)

        if not arquivos:
            resultado = analisar_rotulo(fotos, nome_produto)
            resultado["via_api"] = False
            return resultado

        resposta = requests.post(
            f"{API_URL}/analisar",
            data={"nome_produto": nome_produto},
            files=arquivos,
            timeout=600
        )

        if resposta.status_code == 200:
            resultado = resposta.json()
            resultado["via_api"] = True
            return resultado

        print(f"API retornou HTTP {resposta.status_code}: {resposta.text}")

    except Exception as erro:
        print(f"Falha na API local: {erro}")

    finally:
        for handle in handles:
            handle.close()

    resultado = analisar_rotulo(fotos, nome_produto)
    resultado["via_api"] = False
    return resultado


# ============================================================
# INTERFACE TKINTER
# ============================================================
class RegulaRotuloApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("RegulaRotulo — Conformidade de Alimentos")
        self.geometry("1100x760")
        self.minsize(920, 650)
        self.configure(bg=AZUL_MARINHO)

        self.dados = carregar_dados()
        self.projetos = self.dados.get("projetos", [])
        self.wizard = {}
        self.fotos = {
            "principal": None,
            "nutricional": None,
            "ingredientes": None,
            "outros": None
        }
        self.ultima_analise = None
        self.projeto_aberto = None

        self.container = tk.Frame(self, bg=AZUL_MARINHO)
        self.container.pack(fill="both", expand=True)

        self.frames = {}
        telas = (
            HomeFrame, NovoProjetoFrame, FotosFrame, RelatorioFrame,
            AtividadesFrame, NormasFrame, DetalheProjetoFrame
        )

        for classe in telas:
            frame = classe(self.container, self)
            self.frames[classe.__name__] = frame
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.mostrar("HomeFrame")

    def mostrar(self, nome):
        frame = self.frames[nome]
        frame.tkraise()
        if hasattr(frame, "ao_mostrar"):
            frame.ao_mostrar()

    def salvar(self):
        self.dados["projetos"] = self.projetos
        salvar_dados(self.dados)

    def abrir_projeto_por_nome(self, nome):
        encontrados = encontrar_projeto(self.projetos, nome)
        if not encontrados:
            return False
        self.projeto_aberto = encontrados[0]
        self.mostrar("DetalheProjetoFrame")
        return True


def encontrar_projeto(projetos, termo):
    termo = (termo or "").strip()
    if not termo:
        return list(projetos)

    exato = busca_binaria_por_nome_projeto(projetos, termo)
    if exato is not None:
        return [exato]

    return busca_sequencial(projetos, termo)


def busca_binaria_por_nome_projeto(projetos, nome):
    alvo = (nome or "").strip().casefold()
    ordenados = sorted(
        projetos,
        key=lambda projeto: str(projeto.get("nome", "")).casefold()
    )

    esquerda, direita = 0, len(ordenados) - 1
    while esquerda <= direita:
        meio = (esquerda + direita) // 2
        nome_meio = str(ordenados[meio].get("nome", "")).casefold()

        if nome_meio == alvo:
            return ordenados[meio]
        if nome_meio < alvo:
            esquerda = meio + 1
        else:
            direita = meio - 1

    return None


class BaseFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=CINZA_CLARO)
        self.app = app

    def botao(self, parent, texto, comando, tipo="primary", **kwargs):
        paleta = {
            "primary": (AMARELO, PRETO, AMARELO_ESCURO),
            "outline": (BRANCO, AZUL_MARINHO, CINZA_CLARO),
            "dark": (AZUL_MARINHO, BRANCO, AZUL_ESCURO),
            "danger": (VERMELHO, BRANCO, "#DC2626")
        }
        fundo, texto_cor, ativo = paleta.get(tipo, paleta["primary"])

        return tk.Button(
            parent,
            text=texto,
            command=comando,
            bg=fundo,
            fg=texto_cor,
            activebackground=ativo,
            activeforeground=texto_cor,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=7,
            **kwargs
        )

    def header(self, titulo, voltar=False, destino="HomeFrame"):
        barra = tk.Frame(self, bg=AZUL_MARINHO, height=60)
        barra.pack(fill="x")
        barra.pack_propagate(False)

        if voltar:
            tk.Button(
                barra,
                text="←",
                command=lambda: self.app.mostrar(destino),
                bg=AZUL_MARINHO,
                fg=BRANCO,
                font=("Segoe UI", 17),
                relief="flat",
                cursor="hand2"
            ).pack(side="left", padx=12)

        tk.Label(
            barra, text=titulo, font=("Segoe UI", 15, "bold"),
            bg=AZUL_MARINHO, fg=BRANCO
        ).pack(side="left", padx=10, pady=12)

        tk.Label(
            barra, text="RegulaRotulo", font=("Segoe UI", 10, "bold"),
            bg=AZUL_MARINHO, fg=AMARELO
        ).pack(side="right", padx=18)


class HomeFrame(BaseFrame):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Início")
        self.termo = tk.StringVar()

        topo = tk.Frame(self, bg=CINZA_CLARO)
        topo.pack(fill="x", padx=24, pady=16)

        tk.Label(
            topo, text="Olá! Pronto para verificar rótulos?",
            font=("Segoe UI", 18, "bold"),
            bg=CINZA_CLARO, fg=AZUL_MARINHO
        ).pack(anchor="w")

        motores = []
        motores.append("Docling ✓" if DOCLING_OK else "Docling não instalado")
        motores.append("Tesseract ✓" if TESSERACT_OK else "Tesseract não instalado")
        motores.append("API ✓" if API_OK else "API indisponível")

        tk.Label(
            topo, text="  |  ".join(motores),
            font=("Segoe UI", 9, "bold"),
            bg=CINZA_CLARO, fg=VERDE if DOCLING_OK else AMARELO
        ).pack(anchor="w", pady=(4, 10))

        acoes = tk.Frame(topo, bg=CINZA_CLARO)
        acoes.pack(anchor="w")

        self.botao(
            acoes, "＋ Novo Projeto",
            lambda: app.mostrar("NovoProjetoFrame")
        ).pack(side="left", padx=(0, 8))

        self.botao(
            acoes, "Atividades",
            lambda: app.mostrar("AtividadesFrame"),
            tipo="outline"
        ).pack(side="left", padx=4)

        self.botao(
            acoes, "Normas",
            lambda: app.mostrar("NormasFrame"),
            tipo="dark"
        ).pack(side="left", padx=4)

        self.resumo = tk.Frame(self, bg=CINZA_CLARO)
        self.resumo.pack(fill="x", padx=24, pady=4)

        self.cards = []
        for titulo, cor in [
            ("Total de projetos", AMARELO),
            ("Conformes", VERDE),
            ("Com pendências", VERMELHO)
        ]:
            card = tk.Frame(self.resumo, bg=BRANCO, padx=18, pady=10)
            card.pack(side="left", padx=(0, 10))
            valor = tk.Label(
                card, text="0", font=("Segoe UI", 21, "bold"),
                bg=BRANCO, fg=cor
            )
            valor.pack(anchor="w")
            tk.Label(
                card, text=titulo, font=("Segoe UI", 9),
                bg=BRANCO, fg=CINZA
            ).pack(anchor="w")
            self.cards.append(valor)

        busca = tk.Frame(self, bg=CINZA_CLARO)
        busca.pack(fill="x", padx=24, pady=(12, 4))

        tk.Label(
            busca, text="Buscar projeto:",
            font=("Segoe UI", 10, "bold"),
            bg=CINZA_CLARO, fg=AZUL_MARINHO
        ).pack(side="left")

        tk.Entry(
            busca, textvariable=self.termo, width=30,
            font=("Segoe UI", 10)
        ).pack(side="left", padx=8, ipady=4)

        self.botao(busca, "Buscar", self.ao_mostrar).pack(side="left")
        self.botao(busca, "Limpar", self.limpar, tipo="outline").pack(side="left", padx=5)

        tk.Label(
            self, text="Projetos salvos — clique para abrir",
            font=("Segoe UI", 12, "bold"),
            bg=CINZA_CLARO, fg=AZUL_MARINHO
        ).pack(anchor="w", padx=24, pady=(12, 4))

        self.lista = tk.Frame(self, bg=CINZA_CLARO)
        self.lista.pack(fill="both", expand=True, padx=24, pady=(0, 12))

    def limpar(self):
        self.termo.set("")
        self.ao_mostrar()

    def ao_mostrar(self):
        projetos = self.app.projetos
        self.cards[0].config(text=str(len(projetos)))
        self.cards[1].config(
            text=str(sum(p.get("status") == "conforme" for p in projetos))
        )
        self.cards[2].config(
            text=str(sum(p.get("status") == "pendencias" for p in projetos))
        )

        for widget in self.lista.winfo_children():
            widget.destroy()

        termo = self.termo.get().strip()
        encontrados = encontrar_projeto(projetos, termo) if termo else list(projetos)

        if not encontrados:
            tk.Label(
                self.lista, text="Nenhum projeto encontrado.",
                bg=CINZA_CLARO, fg=CINZA, font=("Segoe UI", 11)
            ).pack(pady=30)
            return

        for projeto in encontrados[:30]:
            card = tk.Frame(
                self.lista, bg=BRANCO, padx=14, pady=10, cursor="hand2"
            )
            card.pack(fill="x", pady=4)

            def abrir(event=None, item=projeto):
                self.app.projeto_aberto = item
                self.app.mostrar("DetalheProjetoFrame")

            card.bind("<Button-1>", abrir)

            tk.Label(
                card, text=projeto.get("nome", ""),
                font=("Segoe UI", 11, "bold"),
                bg=BRANCO, fg=PRETO
            ).pack(anchor="w")

            tk.Label(
                card,
                text=f"{projeto.get('categoria', '')}  |  {projeto.get('data', '')}  |  {projeto.get('status', '')}",
                font=("Segoe UI", 9), bg=BRANCO, fg=CINZA
            ).pack(anchor="w")

            for filho in card.winfo_children():
                filho.bind("<Button-1>", abrir)


class NovoProjetoFrame(BaseFrame):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Novo Projeto", voltar=True)

        form = tk.Frame(self, bg=CINZA_CLARO, padx=38, pady=20)
        form.pack(fill="both", expand=True)

        tk.Label(
            form, text="Tipo de produto *",
            font=("Segoe UI", 10, "bold"),
            bg=CINZA_CLARO, fg=AZUL_MARINHO
        ).pack(anchor="w")

        self.tipo = ttk.Combobox(
            form,
            values=[
                "Leite", "Queijo", "Iogurte", "Manteiga",
                "Ovos", "Carnes", "Pescado", "Mel", "Outros"
            ],
            state="readonly",
            width=42
        )
        self.tipo.pack(anchor="w", pady=(4, 12), ipady=3)

        tk.Label(
            form, text="Nome do produto *",
            font=("Segoe UI", 10, "bold"),
            bg=CINZA_CLARO, fg=AZUL_MARINHO
        ).pack(anchor="w")

        self.nome = tk.Entry(form, width=46, font=("Segoe UI", 11))
        self.nome.pack(anchor="w", pady=(4, 12), ipady=5)

        tk.Label(
            form, text="Observações",
            font=("Segoe UI", 10, "bold"),
            bg=CINZA_CLARO, fg=AZUL_MARINHO
        ).pack(anchor="w")

        self.obs = tk.Text(form, width=46, height=4, font=("Segoe UI", 10))
        self.obs.pack(anchor="w", pady=(4, 12))

        self.atributos = {}
        linha = tk.Frame(form, bg=CINZA_CLARO)
        linha.pack(anchor="w", pady=5)

        for atributo in [
            "Sem glúten", "Com lactose", "Orgânico", "Sem conservantes"
        ]:
            variavel = tk.BooleanVar()
            self.atributos[atributo] = variavel
            tk.Checkbutton(
                linha, text=atributo, variable=variavel,
                bg=CINZA_CLARO, fg=AZUL_MARINHO,
                selectcolor=AMARELO
            ).pack(side="left", padx=(0, 10))

        rodape = tk.Frame(self, bg=BRANCO, pady=10)
        rodape.pack(side="bottom", fill="x")

        self.botao(
            rodape, "Cancelar",
            lambda: app.mostrar("HomeFrame"),
            tipo="outline"
        ).pack(side="left", padx=24)

        self.botao(
            rodape, "Próximo: arquivos →", self.proximo
        ).pack(side="right", padx=24)

    def proximo(self):
        tipo = self.tipo.get()
        nome = self.nome.get().strip()

        if not tipo or not nome:
            messagebox.showerror("Campos obrigatórios", "Preencha tipo e nome do produto.")
            return

        existente = busca_binaria_por_nome_projeto(self.app.projetos, nome)
        if existente and not messagebox.askyesno(
            "Nome repetido", "Já existe um projeto com esse nome. Deseja continuar?"
        ):
            return

        self.app.wizard = {
            "tipo": tipo,
            "nome": nome,
            "obs": self.obs.get("1.0", tk.END).strip(),
            "atributos": [
                chave for chave, valor in self.atributos.items() if valor.get()
            ]
        }
        self.app.mostrar("FotosFrame")


class FotosFrame(BaseFrame):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Arquivos e Fotos do Rótulo", voltar=True, destino="NovoProjetoFrame")

        tk.Label(
            self,
            text="Selecione os arquivos de cada parte do rótulo. Imagens e PDFs são aceitos.",
            font=("Segoe UI", 10),
            bg=CINZA_CLARO, fg=CINZA
        ).pack(pady=(10, 5))

        self.labels = {}
        self.faces = [
            ("principal", "1. Painel principal"),
            ("nutricional", "2. Tabela nutricional"),
            ("ingredientes", "3. Ingredientes e alergênicos"),
            ("outros", "4. Outros lados/documentos")
        ]

        for chave, titulo in self.faces:
            linha = tk.Frame(self, bg=BRANCO, padx=12, pady=8)
            linha.pack(fill="x", padx=32, pady=3)

            tk.Label(
                linha, text=titulo, width=29, anchor="w",
                font=("Segoe UI", 9, "bold"),
                bg=BRANCO, fg=AZUL_MARINHO
            ).pack(side="left")

            label = tk.Label(
                linha, text="Nenhum arquivo selecionado",
                width=32, anchor="w", bg=BRANCO, fg=CINZA
            )
            label.pack(side="left", padx=4)
            self.labels[chave] = label

            tk.Button(
                linha, text="Limpar",
                command=lambda c=chave: self.limpar(c),
                bg=CINZA_CLARO, fg=VERMELHO, relief="flat"
            ).pack(side="right", padx=3)

            tk.Button(
                linha, text="Escolher",
                command=lambda c=chave: self.escolher(c),
                bg=AMARELO, fg=PRETO, relief="flat"
            ).pack(side="right", padx=3)

        # Busca de arquivos por nome
        busca_box = tk.LabelFrame(
            self, text="Localizar arquivo pelo nome",
            bg=CINZA_CLARO, fg=AZUL_MARINHO,
            font=("Segoe UI", 10, "bold"), padx=10, pady=8
        )
        busca_box.pack(fill="both", expand=True, padx=32, pady=10)

        topo_busca = tk.Frame(busca_box, bg=CINZA_CLARO)
        topo_busca.pack(fill="x")

        self.pasta_var = tk.StringVar(value=str(PASTA_ARQUIVOS))
        tk.Entry(
            topo_busca, textvariable=self.pasta_var,
            font=("Segoe UI", 9)
        ).pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=3)

        self.botao(
            topo_busca, "Escolher pasta", self.escolher_pasta,
            tipo="outline"
        ).pack(side="left")

        linha_busca = tk.Frame(busca_box, bg=CINZA_CLARO)
        linha_busca.pack(fill="x", pady=7)

        self.termo_arquivo = tk.StringVar()
        entrada = tk.Entry(
            linha_busca, textvariable=self.termo_arquivo,
            font=("Segoe UI", 10)
        )
        entrada.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=4)
        entrada.bind("<KeyRelease>", lambda evento: self.atualizar_resultados())

        self.botao(
            linha_busca, "Buscar agora", self.atualizar_resultados
        ).pack(side="left")

        tk.Label(
            busca_box,
            text="Digite o nome completo ou apenas parte do nome. Dê dois cliques no resultado para selecionar.",
            bg=CINZA_CLARO, fg=CINZA, font=("Segoe UI", 8)
        ).pack(anchor="w")

        lista_frame = tk.Frame(busca_box, bg=CINZA_CLARO)
        lista_frame.pack(fill="both", expand=True, pady=(5, 0))

        self.lista_arquivos = tk.Listbox(
            lista_frame, height=5, font=("Segoe UI", 9),
            selectbackground=AZUL_MARINHO
        )
        self.lista_arquivos.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(
            lista_frame, orient="vertical",
            command=self.lista_arquivos.yview
        )
        scroll.pack(side="right", fill="y")
        self.lista_arquivos.config(yscrollcommand=scroll.set)
        self.lista_arquivos.bind("<Double-Button-1>", self.selecionar_resultado)

        rodape = tk.Frame(self, bg=BRANCO, pady=9)
        rodape.pack(side="bottom", fill="x")

        self.botao(
            rodape, "Voltar",
            lambda: app.mostrar("NovoProjetoFrame"),
            tipo="outline"
        ).pack(side="left", padx=24)

        self.botao(
            rodape, "Analisar rótulo →", self.proximo
        ).pack(side="right", padx=24)

        self.arquivos_indexados = []
        self.resultados_atual = []
        self.atualizar_index()

    def escolher_pasta(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta de rótulos")
        if pasta:
            self.pasta_var.set(pasta)
            self.atualizar_index()

    def atualizar_index(self):
        self.arquivos_indexados = indexar_arquivos(self.pasta_var.get())
        self.atualizar_resultados()

    def atualizar_resultados(self):
        if not hasattr(self, "lista_arquivos"):
            return

        termo = self.termo_arquivo.get()
        self.resultados_atual = procurar_arquivo(
            self.arquivos_indexados, termo
        )

        self.lista_arquivos.delete(0, tk.END)

        for caminho in self.resultados_atual[:300]:
            self.lista_arquivos.insert(
                tk.END, f"{caminho.name}    —    {caminho.parent}"
            )

        if not self.resultados_atual:
            self.lista_arquivos.insert(tk.END, "Nenhum arquivo encontrado.")

    def escolher(self, chave):
        caminho = filedialog.askopenfilename(
            title=f"Arquivo — {chave}",
            filetypes=[
                ("Imagens e PDFs", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.pdf"),
                ("Todos os arquivos", "*.*")
            ]
        )
        if caminho:
            self.definir_arquivo(chave, caminho)

    def selecionar_resultado(self, evento=None):
        selecao = self.lista_arquivos.curselection()
        if not selecao or not self.resultados_atual:
            return

        indice = selecao[0]
        if indice >= len(self.resultados_atual):
            return

        caminho = self.resultados_atual[indice]

        janela = tk.Toplevel(self)
        janela.title("Selecionar destino")
        janela.geometry("330x190")
        janela.configure(bg=CINZA_CLARO)
        janela.transient(self)
        janela.grab_set()

        tk.Label(
            janela, text=f"Usar {caminho.name} em:",
            wraplength=290, bg=CINZA_CLARO,
            fg=AZUL_MARINHO, font=("Segoe UI", 10, "bold")
        ).pack(padx=12, pady=12)

        destino = tk.StringVar(value="principal")
        combo = ttk.Combobox(
            janela, textvariable=destino,
            values=[chave for chave, _ in self.faces],
            state="readonly"
        )
        combo.pack(padx=12, pady=5)

        def confirmar():
            self.definir_arquivo(destino.get(), str(caminho))
            janela.destroy()

        self.botao(janela, "Selecionar arquivo", confirmar).pack(pady=12)

    def definir_arquivo(self, chave, caminho):
        outros = [
            valor for face, valor in self.app.fotos.items()
            if face != chave and valor
        ]

        if arquivo_ja_selecionado(outros, caminho):
            if not messagebox.askyesno(
                "Arquivo repetido",
                "Esse arquivo já está associado a outra face. Deseja utilizá-lo mesmo assim?"
            ):
                return

        self.app.fotos[chave] = caminho
        self.labels[chave].config(
            text=Path(caminho).name, fg=VERDE
        )

    def limpar(self, chave):
        self.app.fotos[chave] = None
        self.labels[chave].config(
            text="Nenhum arquivo selecionado", fg=CINZA
        )

    def ao_mostrar(self):
        for chave, label in self.labels.items():
            caminho = self.app.fotos.get(chave)
            label.config(
                text=Path(caminho).name if caminho else "Nenhum arquivo selecionado",
                fg=VERDE if caminho else CINZA
            )
        self.atualizar_index()

    def proximo(self):
        if not any(self.app.fotos.values()):
            if not messagebox.askyesno(
                "Sem arquivos",
                "Nenhum arquivo foi selecionado. Deseja gerar uma análise mesmo assim?"
            ):
                return

        # A análise é executada em thread para não congelar a interface.
        self.app.mostrar("RelatorioFrame")
        relatorio = self.app.frames["RelatorioFrame"]
        relatorio.mostrar_processando()

        nome = self.app.wizard.get("nome", "Produto")
        fotos = dict(self.app.fotos)

        def executar():
            resultado = analisar_via_api(fotos, nome)
            self.after(0, lambda: relatorio.finalizar_analise(resultado))

        threading.Thread(target=executar, daemon=True).start()


class RelatorioFrame(BaseFrame):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.ncs_count = 0
        self.header("Relatório de Conformidade", voltar=True, destino="FotosFrame")

        self.titulo = tk.Label(
            self, text="", font=("Segoe UI", 15, "bold"),
            bg=CINZA_CLARO, fg=AZUL_MARINHO
        )
        self.titulo.pack(pady=(15, 5))

        self.lbl_ocr = tk.Label(
            self, text="", font=("Segoe UI", 9),
            bg=CINZA_CLARO, fg=CINZA
        )
        self.lbl_ocr.pack()

        scores = tk.Frame(self, bg=CINZA_CLARO)
        scores.pack(pady=8)

        self.score_labels = []
        for nome, cor in [
            ("Alto", VERDE), ("Médio", AMARELO), ("Baixo", VERMELHO)
        ]:
            card = tk.Frame(scores, bg=BRANCO, padx=22, pady=10)
            card.pack(side="left", padx=7)

            valor = tk.Label(
                card, text="--", font=("Segoe UI", 19, "bold"),
                bg=BRANCO, fg=cor
            )
            valor.pack()

            tk.Label(
                card, text=nome, bg=BRANCO, fg=CINZA
            ).pack()

            self.score_labels.append(valor)

        tk.Label(
            self, text="Não conformidades / itens para revisão",
            font=("Segoe UI", 12, "bold"),
            bg=CINZA_CLARO, fg=AZUL_MARINHO
        ).pack(pady=(10, 5))

        self.nc_frame = tk.Frame(self, bg=BRANCO, padx=16, pady=12)
        self.nc_frame.pack(fill="both", expand=True, padx=36, pady=5)

        self.textos_frame = tk.Frame(self, bg=CINZA_CLARO)
        self.textos_frame.pack(fill="x", padx=36, pady=3)

        rodape = tk.Frame(self, bg=BRANCO, pady=9)
        rodape.pack(side="bottom", fill="x")

        self.botao(
            rodape, "Voltar",
            lambda: app.mostrar("FotosFrame"),
            tipo="outline"
        ).pack(side="left", padx=24)

        self.botao(
            rodape, "Salvar Projeto",
            self.salvar_projeto
        ).pack(side="right", padx=24)

    def mostrar_processando(self):
        self.titulo.config(text=self.app.wizard.get("nome", "Produto"))
        self.lbl_ocr.config(text="Processando arquivos com Docling/Tesseract...")
        for widget in self.nc_frame.winfo_children():
            widget.destroy()
        tk.Label(
            self.nc_frame, text="Aguarde. A análise pode levar alguns instantes.",
            bg=BRANCO, fg=AZUL_MARINHO,
            font=("Segoe UI", 10)
        ).pack(anchor="w")

    def finalizar_analise(self, resultado):
        self.app.ultima_analise = resultado
        self.ao_mostrar()

    def ao_mostrar(self):
        nome = self.app.wizard.get("nome", "Produto")
        self.titulo.config(text=nome)

        analise = self.app.ultima_analise
        if not analise:
            self.lbl_ocr.config(text="Aguardando análise...")
            return

        motor = analise.get("motor", "nenhum")
        via = "API" if analise.get("via_api") else "local"
        self.lbl_ocr.config(
            text=f"Mecanismo: {motor.upper()} | Processamento: {via}",
            fg=VERDE if motor != "nenhum" else AMARELO
        )

        scores = analise.get("scores", {})
        self.score_labels[0].config(text=f"{scores.get('alto', 0)}%")
        self.score_labels[1].config(text=f"{scores.get('medio', 0)}%")
        self.score_labels[2].config(text=f"{scores.get('baixo', 0)}%")

        for widget in self.nc_frame.winfo_children():
            widget.destroy()

        nao_conformidades = analise.get("nao_conformidades") or analise.get("ncs") or []
        self.ncs_count = len(nao_conformidades)

        if not nao_conformidades:
            tk.Label(
                self.nc_frame, text="Nenhum item foi sinalizado pelo protótipo.",
                font=("Segoe UI", 10), bg=BRANCO, fg=VERDE
            ).pack(anchor="w")
        else:
            for item in nao_conformidades:
                tk.Label(
                    self.nc_frame, text=f"• {item}",
                    font=("Segoe UI", 9), bg=BRANCO, fg=PRETO,
                    wraplength=850, justify="left"
                ).pack(anchor="w", pady=3)

        aviso = (
            "IMPORTANTE: resultado preliminar e experimental. OCR pode falhar; "
            "a ferramenta não substitui responsável técnico, legislação vigente "
            "ou avaliação/aprovação do órgão competente."
        )
        tk.Label(
            self.nc_frame, text=aviso, wraplength=850,
            bg=BRANCO, fg=CINZA, justify="left",
            font=("Segoe UI", 8, "italic")
        ).pack(anchor="w", pady=(12, 2))

    def salvar_projeto(self):
        if not self.app.ultima_analise:
            messagebox.showwarning("Aguarde", "A análise ainda não foi concluída.")
            return

        mapa_categoria = {
            "Leite": "laticinios", "Iogurte": "laticinios",
            "Manteiga": "laticinios", "Queijo": "queijos",
            "Ovos": "ovos", "Carnes": "carnes",
            "Pescado": "pescado", "Mel": "outros", "Outros": "outros"
        }

        analise = self.app.ultima_analise
        quantidade = len(
            analise.get("nao_conformidades") or analise.get("ncs") or []
        )
        status = (
            "conforme" if quantidade <= 1
            else "analise" if quantidade <= 2
            else "pendencias"
        )

        projeto = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "nome": self.app.wizard.get("nome", "Produto"),
            "categoria": mapa_categoria.get(
                self.app.wizard.get("tipo", "Outros"), "outros"
            ),
            "tipo": self.app.wizard.get("tipo", "Outros"),
            "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "status": status,
            "pendencias": quantidade,
            "obs": self.app.wizard.get("obs", ""),
            "atributos": self.app.wizard.get("atributos", []),
            "arquivos": {
                chave: Path(caminho).name if caminho else None
                for chave, caminho in self.app.fotos.items()
            },
            "motor_ocr": analise.get("motor", "nenhum")
        }

        self.app.projetos.insert(0, projeto)
        self.app.salvar()

        self.app.fotos = {
            chave: None for chave in self.app.fotos
        }
        self.app.wizard = {}
        self.app.ultima_analise = None

        messagebox.showinfo("Sucesso", "Projeto salvo no histórico.")
        self.app.mostrar("HomeFrame")


class DetalheProjetoFrame(BaseFrame):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Detalhe do Projeto", voltar=True)

        self.titulo = tk.Label(
            self, text="", font=("Segoe UI", 15, "bold"),
            bg=CINZA_CLARO, fg=AZUL_MARINHO
        )
        self.titulo.pack(pady=(18, 5))

        self.meta = tk.Label(
            self, text="", font=("Segoe UI", 10),
            bg=CINZA_CLARO, fg=CINZA
        )
        self.meta.pack(pady=3)

        self.status_lbl = tk.Label(
            self, text="", font=("Segoe UI", 11, "bold"),
            bg=CINZA_CLARO
        )
        self.status_lbl.pack(pady=8)

        self.info = tk.Frame(self, bg=BRANCO, padx=18, pady=14)
        self.info.pack(fill="x", padx=38, pady=8)

        rodape = tk.Frame(self, bg=BRANCO, pady=9)
        rodape.pack(side="bottom", fill="x")

        self.botao(
            rodape, "Voltar",
            lambda: app.mostrar("HomeFrame"),
            tipo="outline"
        ).pack(side="left", padx=24)

        self.botao(
            rodape, "Excluir",
            self.excluir,
            tipo="danger"
        ).pack(side="left", padx=5)

        self.botao(
            rodape, "Reanalisar com novos arquivos",
            self.reanalisar
        ).pack(side="right", padx=24)

    def ao_mostrar(self):
        projeto = self.app.projeto_aberto
        if not projeto:
            self.app.mostrar("HomeFrame")
            return

        self.titulo.config(text=projeto.get("nome", ""))
        self.meta.config(
            text=f"{projeto.get('categoria', '')} | {projeto.get('data', '')}"
        )

        status = projeto.get("status", "rascunho")
        cores = {
            "conforme": VERDE,
            "pendencias": VERMELHO,
            "analise": AMARELO,
            "rascunho": CINZA
        }
        self.status_lbl.config(text=status.upper(), fg=cores.get(status, CINZA))

        for widget in self.info.winfo_children():
            widget.destroy()

        dados = [
            ("Tipo", projeto.get("tipo", "")),
            ("Pendências registradas", projeto.get("pendencias", 0)),
            ("Mecanismo OCR", projeto.get("motor_ocr", "não registrado")),
            ("Observações", projeto.get("obs", "")),
            ("Atributos", ", ".join(projeto.get("atributos", []))),
            ("Arquivos", ", ".join(
                nome for nome in projeto.get("arquivos", {}).values() if nome
            ))
        ]

        for titulo, valor in dados:
            tk.Label(
                self.info, text=f"{titulo}: {valor or '—'}",
                bg=BRANCO, fg=PRETO, font=("Segoe UI", 9),
                wraplength=850, justify="left"
            ).pack(anchor="w", pady=3)

    def reanalisar(self):
        projeto = self.app.projeto_aberto or {}
        self.app.wizard = {
            "tipo": projeto.get("tipo", "Outros"),
            "nome": projeto.get("nome", ""),
            "obs": projeto.get("obs", ""),
            "atributos": projeto.get("atributos", [])
        }
        self.app.fotos = {
            "principal": None,
            "nutricional": None,
            "ingredientes": None,
            "outros": None
        }
        self.app.ultima_analise = None
        self.app.mostrar("FotosFrame")

    def excluir(self):
        projeto = self.app.projeto_aberto
        if not projeto:
            return

        nome = projeto.get("nome", "")
        if not messagebox.askyesno("Excluir projeto", f'Excluir "{nome}"?'):
            return

        self.app.projetos = [
            item for item in self.app.projetos
            if item.get("id") != projeto.get("id")
        ]
        self.app.salvar()
        self.app.projeto_aberto = None
        self.app.mostrar("HomeFrame")


class AtividadesFrame(BaseFrame):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Atividades Salvas", voltar=True)
        self.termo = tk.StringVar()

        busca = tk.Frame(self, bg=CINZA_CLARO)
        busca.pack(fill="x", padx=24, pady=12)

        tk.Entry(
            busca, textvariable=self.termo,
            font=("Segoe UI", 10), width=32
        ).pack(side="left", padx=6, ipady=4)

        self.botao(busca, "Buscar", self.ao_mostrar).pack(side="left")

        self.lista = tk.Frame(self, bg=CINZA_CLARO)
        self.lista.pack(fill="both", expand=True, padx=24, pady=8)

    def ao_mostrar(self):
        for widget in self.lista.winfo_children():
            widget.destroy()

        termo = self.termo.get().strip()
        projetos = encontrar_projeto(self.app.projetos, termo) if termo else self.app.projetos

        if not projetos:
            tk.Label(
                self.lista, text="Nenhuma atividade encontrada.",
                bg=CINZA_CLARO, fg=CINZA
            ).pack(pady=30)
            return

        for projeto in projetos:
            card = tk.Frame(self.lista, bg=BRANCO, padx=14, pady=10, cursor="hand2")
            card.pack(fill="x", pady=4)

            def abrir(event=None, item=projeto):
                self.app.projeto_aberto = item
                self.app.mostrar("DetalheProjetoFrame")

            card.bind("<Button-1>", abrir)

            tk.Label(
                card, text=projeto.get("nome", ""),
                font=("Segoe UI", 10, "bold"),
                bg=BRANCO, fg=PRETO
            ).pack(anchor="w")

            tk.Label(
                card,
                text=f"{projeto.get('categoria', '')} | {projeto.get('data', '')}",
                bg=BRANCO, fg=CINZA, font=("Segoe UI", 9)
            ).pack(anchor="w")

            for filho in card.winfo_children():
                filho.bind("<Button-1>", abrir)


class NormasFrame(BaseFrame):
    def __init__(self, parent, app):
        super().__init__(parent, app)
        self.header("Referências normativas", voltar=True)

        normas = [
            ("RDC nº 429/2020", "Requisitos de rotulagem nutricional dos alimentos embalados."),
            ("IN nº 75/2020", "Requisitos técnicos para declaração da rotulagem nutricional."),
            ("RDC nº 26/2015", "Requisitos para rotulagem obrigatória dos principais alimentos que causam alergias alimentares."),
            ("RDC nº 727/2022", "Requisitos gerais de rotulagem dos alimentos embalados."),
            ("Lei nº 10.674/2003", "Obrigatoriedade de informar sobre a presença de glúten.")
        ]

        for titulo, descricao in normas:
            card = tk.Frame(self, bg=BRANCO, padx=16, pady=12)
            card.pack(fill="x", padx=28, pady=5)

            tk.Label(
                card, text=titulo, font=("Segoe UI", 11, "bold"),
                bg=BRANCO, fg=AZUL_MARINHO
            ).pack(anchor="w")

            tk.Label(
                card, text=descricao, font=("Segoe UI", 9),
                bg=BRANCO, fg=CINZA, wraplength=900, justify="left"
            ).pack(anchor="w", pady=(3, 0))

        tk.Label(
            self,
            text="Consulte sempre a versão vigente das normas e as regras específicas do produto e do órgão competente.",
            bg=CINZA_CLARO, fg=CINZA, font=("Segoe UI", 8, "italic"),
            wraplength=900
        ).pack(anchor="w", padx=30, pady=12)


# ============================================================
# EXECUÇÃO
# ============================================================
if __name__ == "__main__":
    PASTA_ARQUIVOS.mkdir(parents=True, exist_ok=True)
    iniciar_api_background()
    app = RegulaRotuloApp()
    app.mainloop()
