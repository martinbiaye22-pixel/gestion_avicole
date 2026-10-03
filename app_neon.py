import os
import io
from datetime import datetime, timedelta, date
import pandas as pd
import calendar
from random import randint
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, current_app, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func, extract, event, or_, and_, asc, desc
from reportlab.lib.pagesizes import letter, A4, A5, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import inch
from sqlalchemy.orm import joinedload

app = Flask(__name__)

# --- CONFIGURATION POSTGRESQL NEON ---
database_url = os.environ.get ("DATABASE_URL")

if not database_url:
    raise RuntimeError(
        "DATABASE_URL n'est pas définie. "
        "Définissez-la avec votre chaîne de connexion PostgreSQL Neon."
    )

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY',
    'cle-secrete-de-developpement-a-remplacer-en-production'
)

# --- CONFIGURATION DYNAMIQUE DES CHEMINS D'ACCÈS ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static/uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

db = SQLAlchemy()
db.init_app(app)

def allowed_file(filename):
   return '.' in filename and filename.rsplit('.', 1)[-1].lower() in ALLOWED_EXTENSIONS

# -------------------------------------------------------
# TABLES HISTORIQUES MAINTENUES
# -------------------------------------------------------
class Users(db.Model):
    __tablename__ = 'users'
    NumUser = db.Column(db.Integer, primary_key=True, autoincrement=True)
    NomUtilisateur = db.Column(db.String(100), nullable=False, unique=True)
    MotPasse = db.Column(db.String(255), nullable=False)
    Fonction = db.Column(db.String(100), nullable=False) 
    Adresse = db.Column(db.String(300), nullable=False)
    Telephone = db.Column(db.String(300), nullable=False)
    EstActif = db.Column(db.Boolean, default=True, nullable=False)

    achats = db.relationship('Achat', backref='operateur', lazy=True)
    ventes = db.relationship('Vente', backref='operateur', lazy=True)
    alimentations = db.relationship('Alimentation', backref='operateur', lazy=True)
    mortalites = db.relationship('Mortalite', backref='operateur', lazy=True)
    vaccinations = db.relationship('Vaccination', backref='operateur', lazy=True)
    productions_oeufs = db.relationship('ProductionOeufs', backref='operateur', lazy=True)
    factures = db.relationship('Facture', backref='operateur', lazy=True)
    paiements = db.relationship('Paiement', backref='operateur', lazy=True)

class Configuration(db.Model):
    __tablename__ = 'configuration'
    id = db.Column(db.Integer, primary_key=True)
    cle_invitation = db.Column(db.String(100), nullable=True)
    raison_sociale = db.Column(db.String(200), nullable=True)
    adresse = db.Column(db.String(300), nullable=True)
    telephone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    ninea = db.Column(db.String(100), nullable=True)
    rccm = db.Column(db.String(100), nullable=True)
    logo = db.Column(db.String(255), nullable=True)
    stock_initial_cycle = db.Column(db.Float, nullable=True, default=2580.0)
    ration_fixe_journaliere = db.Column(db.Float, nullable=True, default=86.0)

class JournalSecurite(db.Model):
    __tablename__ = 'journal_securite'
    id_journal = db.Column(db.Integer, primary_key=True)
    date_action = db.Column(db.DateTime, default=datetime.now, nullable=False)
    action_menee = db.Column(db.String(100), nullable=False)
    details = db.Column(db.String(255), nullable=False)
    id_cible = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False)
    
    utilisateur_cible = db.relationship('Users', backref='journaux_securite')

# -------------------------------------------------------
# TABLES D'ASSOCIATION N,N
# -------------------------------------------------------
achat_produit = db.Table('achat_produit',
    db.Column('id_achat', db.Integer, db.ForeignKey('achat.id_achat'), primary_key=True),
    db.Column('id_produit', db.Integer, db.ForeignKey('produit.id_produit'), primary_key=True),
    db.Column('quantite', db.Float, nullable=False, default=0.0),
    db.Column('prix_unitaire', db.Float, nullable=False, default=0.0), 
    db.Column('usage_produit', db.String(50), nullable=False, default='vente') 
)

vente_produit = db.Table('vente_produit',
    db.Column('id_vente', db.Integer, db.ForeignKey('vente.id_vente'), primary_key=True),
    db.Column('id_produit', db.Integer, db.ForeignKey('produit.id_produit'), primary_key=True),
    db.Column('quantite', db.Float, nullable=False, default=0.0),
    db.Column('prix_unitaire', db.Float, nullable=False, default=0.0)
)

# -------------------------------------------------------
# TABLES AGRICOLES & COMPTABLES RECTIFIÉES
# -------------------------------------------------------
class Fournisseur(db.Model):
    __tablename__ = 'fournisseur'
    id_fournisseur = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.String(150), nullable=False)
    telephone = db.Column(db.String(50))
    adresse = db.Column(db.String(200))
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser', ondelete='RESTRICT'), nullable=False)
    
    achats = db.relationship('Achat', backref='fournisseur', lazy=True)
    user = db.relationship('Users', backref=db.backref('fournisseurs_crees', lazy=True))

class Produit(db.Model):
    __tablename__ = 'produit'
    id_produit = db.Column(db.Integer, primary_key=True, autoincrement=True)
    designation = db.Column(db.String(150), nullable=False)
    categorie = db.Column(db.String(100), nullable=False, index=True)
    unite = db.Column(db.String(50), nullable=False)
    prix_vente = db.Column(db.Float, nullable=True, default=0.0)
    prix_achat = db.Column(db.Float, nullable=True, default=0.0)
    stock = db.Column(db.Float, nullable=False, default=0.0)
    date_enregistrement = db.Column(db.Date, nullable=False, default=date.today)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser', ondelete='RESTRICT'), nullable=False)
    
    user = db.relationship('Users', backref=db.backref('produits_enregistres', lazy=True))

class Achat(db.Model):
    __tablename__ = 'achat'
    id_achat = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date_achat = db.Column(db.Date, nullable=False, default=date.today)
    id_fournisseur = db.Column(db.Integer, db.ForeignKey('fournisseur.id_fournisseur'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False)
    produits = db.relationship('Produit', secondary=achat_produit, backref=db.backref('achats', lazy='dynamic'))

class Client(db.Model):
    __tablename__ = 'client'
    id_client = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nom = db.Column(db.String(150), nullable=False)
    telephone = db.Column(db.String(50))
    adresse = db.Column(db.String(200))
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser', ondelete='RESTRICT'), nullable=False)
    
    ventes = db.relationship('Vente', backref='client', lazy=True)
    factures = db.relationship('Facture', backref='client', lazy=True)
    user = db.relationship('Users', backref=db.backref('clients_crees_par_user', lazy=True))

class Vente(db.Model):
    __tablename__ = 'vente'
    id_vente = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date_vente = db.Column(db.Date, nullable=False, default=date.today)
    id_client = db.Column(db.Integer, db.ForeignKey('client.id_client'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False)
    produits = db.relationship('Produit', secondary=vente_produit, backref=db.backref('ventes', lazy='dynamic'))
    facture = db.relationship('Facture', backref='vente', uselist=False, lazy=True)

class LotAvicole(db.Model):
    __tablename__ = 'lot_avicole'
    id_lot = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code_lot = db.Column(db.String(50), nullable=False, unique=True)
    nom_ferme = db.Column(db.String(100))
    type_elevage = db.Column(db.String(100))
    souche = db.Column(db.String(100))
    date_arrivee = db.Column(db.Date, nullable=False, default=date.today)
    effectif_initial = db.Column(db.Integer, default=0)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser', ondelete='SET NULL'), nullable=True)

    user = db.relationship('Users', backref=db.backref('LotAvicole', lazy=True))
    alimentations = db.relationship('Alimentation', backref='lot_avicole', lazy=True)
    mortalites = db.relationship('Mortalite', backref='lot_avicole', lazy=True)
    vaccinations = db.relationship('Vaccination', backref='lot_avicole', lazy=True)
    productions_oeufs = db.relationship('ProductionOeufs', backref='lot_avicole', lazy=True)
  
class SuiviCroissance(db.Model):
    __tablename__ = 'suivi_croissance'
    id_pesee = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date_pesee = db.Column(db.Date, nullable=False, default=date.today)
    poids_moyen = db.Column(db.Float, nullable=False, default=0.0) 
    age_semaines = db.Column(db.Integer, nullable=False) 
    id_lot = db.Column(db.Integer, db.ForeignKey('lot_avicole.id_lot'), nullable=False)
    
    # 🌟 AJOUT : Liaison vers l'utilisateur pour le cloisonnement et la traçabilité
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False)
    
    # Relations d'accès rapide (Jointures automatiques)
    lot_avicole = db.relationship('LotAvicole', backref=db.backref('pesees', lazy=True))
    auteur = db.relationship('Users', backref=db.backref('pesees_saisies', lazy=True))

class Alimentation(db.Model):
    __tablename__ = 'alimentation'
    id_alimentation = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date_alimentation = db.Column(db.Date, nullable=False, default=datetime.now)
    quantite = db.Column(db.Float, default=0.0)
    id_lot = db.Column(db.Integer, db.ForeignKey('lot_avicole.id_lot'), nullable=False)
    id_produit = db.Column(db.Integer, db.ForeignKey('produit.id_produit'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False)
    
    # Relations
    produit = db.relationship('Produit', backref=db.backref('distributions', lazy=True))

class Mortalite(db.Model):
    __tablename__ = 'mortalite'
    id_mortalite = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date_mortalite = db.Column(db.Date, nullable=False, default=datetime.now)
    nombre = db.Column(db.Integer, default=0)
    cause = db.Column(db.String(255))
    id_lot = db.Column(db.Integer, db.ForeignKey('lot_avicole.id_lot'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False)

class Vaccination(db.Model):
    __tablename__ = 'vaccination'
    id_vaccination = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date_vaccination = db.Column(db.Date, nullable=False, default=datetime.now)
    
    # 🌟 MODIFICATION : Liaison directe avec la pharmacie/produit
    id_produit = db.Column(db.Integer, db.ForeignKey('produit.id_produit'), nullable=False)
    # Quantité utilisée lors de l'acte sanitaire (ex: 5 flacons, 2 litres, etc.)
    quantite_utilisee = db.Column(db.Integer, nullable=False, default=1)
    

    dose = db.Column(db.String(50)) # Ex: "2 ml / Litre d'eau"
    id_lot = db.Column(db.Integer, db.ForeignKey('lot_avicole.id_lot'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False)
    
    # Relations d'accès rapide
    produit = db.relationship('Produit', backref=db.backref('vaccinations_associees', lazy=True))
   
   
class ProductionOeufs(db.Model):
    __tablename__ = 'production_oeufs'
    id_production = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date_production = db.Column(db.Date, nullable=False, default=datetime.now)
    nombre_oeufs = db.Column(db.Integer, default=0)
        # (Fin de la classe ProductionOeufs précédente)
    oeufs_casses = db.Column(db.Integer, default=0)
    id_lot = db.Column(db.Integer, db.ForeignKey('lot_avicole.id_lot'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False) # Lié à l'employé


class Facture(db.Model):
    __tablename__ = 'facture'
    id_facture = db.Column(db.Integer, primary_key=True, autoincrement=True)
    numero_facture = db.Column(db.String(100), unique=True, nullable=False)
    date_facture = db.Column(db.Date, nullable=False, default=datetime.now)
    id_vente = db.Column(db.Integer, db.ForeignKey('vente.id_vente'), nullable=True)
    id_client = db.Column(db.Integer, db.ForeignKey('client.id_client'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False) # Lié à l'employé
    statut = db.Column(db.String(50))
    paiements = db.relationship('Paiement', backref='facture', lazy=True)

class Paiement(db.Model):
    __tablename__ = 'paiement'
    id_paiement = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date_paiement = db.Column(db.Date, nullable=False, default=datetime.now)
    montant = db.Column(db.Float, nullable=False, default=0.0)
    mode_paiement = db.Column(db.String(50))
    reference_paiement = db.Column(db.String(100))
    id_facture = db.Column(db.Integer, db.ForeignKey('facture.id_facture'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=False) # Lié à l'employé
    recu = db.relationship('Recu', backref='paiement', uselist=False, lazy=True)

class Recu(db.Model):
    __tablename__ = 'recu'
    id_recu = db.Column(db.Integer, primary_key=True, autoincrement=True)
    numero_recu = db.Column(db.String(100), unique=True, nullable=False)
    date_recu = db.Column(db.Date, nullable=False, default=datetime.now)
    id_paiement = db.Column(db.Integer, db.ForeignKey('paiement.id_paiement'), unique=True, nullable=False)

# -------------------------------------------------------
# TABLES DE GESTION DES DÉPENSES
# -------------------------------------------------------
class TypeDepense(db.Model):
    __tablename__ = 'type_depense'
    id_type_depense = db.Column(db.Integer, primary_key=True, autoincrement=True)
    libelle_type = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    actif = db.Column(db.Boolean, default=True)
    depenses = db.relationship('Depense', backref='type_depense', lazy=True)

class Depense(db.Model):
    __tablename__ = 'depense'

    id_depense = db.Column(db.Integer, primary_key=True)
    montant = db.Column(db.Float, nullable=False)
    date_depense = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    commentaire = db.Column(db.Text, nullable=True)
    id_type_depense = db.Column(db.Integer, db.ForeignKey('type_depense.id_type_depense'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser', ondelete='SET NULL'), nullable=True)
    user = db.relationship('Users', backref=db.backref('depenses', lazy=True))
# -------------------------------------------------------
# TABLES DE GESTION DES RESSOURCES HUMAINES & PAIE
# -------------------------------------------------------
class Employe(db.Model):
    __tablename__ = 'employe'
    id_employe = db.Column(db.Integer, primary_key=True, autoincrement=True)
    matricule = db.Column(db.String(50), unique=True, nullable=False)
    cin = db.Column(db.String(50), unique=True, nullable=False)
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100), nullable=False)
    
    # 🔴 AJOUTS : État civil de l'employé
    date_naissance = db.Column(db.Date, nullable=False) # Obligatoire
    lieu_naissance = db.Column(db.String(150), nullable=False) # Obligatoire
    
    telephone = db.Column(db.String(50), nullable=True)
    adresse = db.Column(db.String(255), nullable=True)
    date_embauche = db.Column(db.Date, nullable=False, default=datetime.now)

    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser'), nullable=True)
    user = db.relationship('Users', backref=db.backref('user', uselist=False), lazy=True)

    # Relations RH
    contrats = db.relationship('Contrat', backref='employe', lazy=True)
    affectations = db.relationship('AffectationPoste', backref='employe', lazy=True)
    salaires = db.relationship('Salaire', backref='employe', lazy=True)
    paies = db.relationship('Paie', backref='employe', lazy=True)

# =======================================================================
# 📜 1. TABLE DES ENGAGEMENTS CONTRACTUELS (Avec Durée)
# =======================================================================
class Contrat(db.Model):
    __tablename__ = 'contrat'
    id_contrat = db.Column(db.Integer, primary_key=True, autoincrement=True)
    type_contrat = db.Column(db.String(50), nullable=False) # Ex: CDD, CDI, Journalier
    date_debut = db.Column(db.Date, nullable=False)
    duree_contrat = db.Column(db.Integer, default=0) # 🔴 AJOUTÉ : Durée en mois (0 si CDI)
    
    id_employe = db.Column(db.Integer, db.ForeignKey('employe.id_employe'), nullable=False)

# =======================================================================
# 💼 2. DICTIONNAIRE DES POSTES ET MÉTIERS DE LA FERME
# =======================================================================
class Poste(db.Model):
    __tablename__ = 'poste'
    id_poste = db.Column(db.Integer, primary_key=True, autoincrement=True)
    libelle_poste = db.Column(db.String(100), nullable=False)
    
    affectations = db.relationship('AffectationPoste', backref='poste', lazy=True)

# =======================================================================
# 📍 3. HISTORIQUE DES AFFECTATIONS DE POSTES DE L'EMPLOYÉ
# =======================================================================
class AffectationPoste(db.Model):
    __tablename__ = 'affectation_poste'
    id_affectation = db.Column(db.Integer, primary_key=True, autoincrement=True)
    id_employe = db.Column(db.Integer, db.ForeignKey('employe.id_employe'), nullable=False)
    id_poste = db.Column(db.Integer, db.ForeignKey('poste.id_poste'), nullable=False)
    date_affectation = db.Column(db.Date, nullable=False) # 🔴 AJOUTÉ : Date précise du mouvement

# =======================================================================
# 💰 4. HISTORIQUE DES RÉMUNÉRATIONS FORFAITAIRES (Mensuel / Par Lot)
# =======================================================================
class Salaire(db.Model):
    __tablename__ = 'salaire'
    id_salaire = db.Column(db.Integer, primary_key=True, autoincrement=True)
    mode_renumeration = db.Column(db.String(50), nullable=False) # 🔴 AJOUTÉ : Mensuel, Par lot, Journalier
    montant = db.Column(db.Float, nullable=False, default=0.0) # Salaire forfaitaire fixe convenu
    date_salaire = db.Column(db.Date, nullable=False) # 🔴 AJOUTÉ : Date de fixation ou d'application
    id_employe = db.Column(db.Integer, db.ForeignKey('employe.id_employe'), nullable=False)


class Paie(db.Model):
    __tablename__ = 'paie'
    id_paie = db.Column(db.Integer, primary_key=True, autoincrement=True)
    periode = db.Column(db.String(50), nullable=False) # Ex: "08-2026"
    date_paie = db.Column(db.Date, nullable=False, default=datetime.now)
    avance = db.Column(db.Float, default=0.0)
    retenue = db.Column(db.Float, default=0.0)
    prime = db.Column(db.Float, default=0.0)
    indemnite = db.Column(db.Float, default=0.0)
    ipres = db.Column(db.Float, default=0.0)
    assurance = db.Column(db.Float, default=0.0)
    impot = db.Column(db.Float, default=0.0)
    id_employe = db.Column(db.Integer, db.ForeignKey('employe.id_employe'), nullable=False)

    bulletin = db.relationship('BulletinSalaire', backref='paie', uselist=False, lazy=True)

class BulletinSalaire(db.Model):
    __tablename__ = 'bulletin_salaire'
    id_bulletin = db.Column(db.Integer, primary_key=True, autoincrement=True)
    numero_bulletin = db.Column(db.String(100), unique=True, nullable=False)
    date_emission = db.Column(db.Date, nullable=False, default=datetime.now)
    id_paie = db.Column(db.Integer, db.ForeignKey('paie.id_paie'), unique=True, nullable=False)

# =======================================================================
# MODULE : ACHATS ET LOGISTIQUE LIÉ À L'UTILISATEUR (USERS)
# =======================================================================

class PaiementAchat(db.Model):
    __tablename__ = 'paiement_achat'
    
    id_paiement_achat = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # RÈGLE DE GESTION : Utilise la date brute du jour de l'opération
    date_paiement = db.Column(db.Date, nullable=False, default=datetime.now)
    montant_paye = db.Column(db.Float, nullable=False, default=0.0)
    mode_paiement = db.Column(db.String(50), nullable=False)
    reference = db.Column(db.String(100), nullable=True)
    
    # Clés étrangères (Foreign Keys)
    id_achat = db.Column(db.Integer, db.ForeignKey('achat.id_achat', ondelete='CASCADE'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser', ondelete='RESTRICT'), nullable=False) # ) ajoutée ici
    
    # OPTIMISATION : Liaisons de jointures automatiques pour le rendu ultra-rapide
    achat = db.relationship('Achat', backref=db.backref('reglements_fournisseurs', cascade='all, delete-orphan', lazy=True))
    user = db.relationship('Users', backref=db.backref('reglements_achats_saisis', lazy=True))



class Investissement(db.Model):
    __tablename__ = 'investissement'
    
    id_investissement = db.Column(db.Integer, primary_key=True, autoincrement=True)
    designation = db.Column(db.String(150), nullable=False)
    categorie = db.Column(db.String(100), nullable=False) # Bâtiment, Matériel, Véhicule...
    date_acquisition = db.Column(db.Date, nullable=False)
    quantite = db.Column(db.Integer, nullable=False, default=1)
    montant = db.Column(db.Float, nullable=False, default=0.0)
    duree_amortissement = db.Column(db.Integer, nullable=False) # En années
    
    id_fournisseur = db.Column(db.Integer, db.ForeignKey('fournisseur.id_fournisseur', ondelete='RESTRICT'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser', ondelete='RESTRICT'), nullable=False)
    
    # Relations d'accès et de suppression en cascade
    amortissements = db.relationship('Amortissement', backref='investissement', cascade='all, delete-orphan', lazy=True)
    paiements = db.relationship('PaiementInvestissement', backref='investissement', cascade='all, delete-orphan', lazy=True)


class Amortissement(db.Model):
    __tablename__ = 'amortissement'
    
    id_amortissement = db.Column(db.Integer, primary_key=True, autoincrement=True)
    annee = db.Column(db.Integer, nullable=False) # Ex: 2026
    montant_amortissement = db.Column(db.Float, nullable=False, default=0.0)
    
    id_investissement = db.Column(db.Integer, db.ForeignKey('investissement.id_investissement', ondelete='CASCADE'), nullable=False)


class PaiementInvestissement(db.Model):
    __tablename__ = 'paiement_investissement'
    
    id_paiement_investissement = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date_paiement = db.Column(db.Date, nullable=False, default= datetime.now)
    montant_paye = db.Column(db.Float, nullable=False, default=0.0)
    mode_paiement = db.Column(db.String(50), nullable=False)
    reference = db.Column(db.String(100), nullable=True)
    
    id_investissement = db.Column(db.Integer, db.ForeignKey('investissement.id_investissement', ondelete='CASCADE'), nullable=False)
    id_user = db.Column(db.Integer, db.ForeignKey('users.NumUser', ondelete='RESTRICT'), nullable=False)

# -------------------------------------------------------
# ROUTES DE NAVIGATION & AUTHENTIFICATION
# -------------------------------------------------------
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    
    # Récupération en base de l'utilisateur connecté pour vérifier son rôle réel
    utilisateur = Users.query.get(session['user_id'])
    if not utilisateur:
        session.clear()
        return redirect(url_for('connexion_get'))
        
    role = utilisateur.Fonction.lower().strip()
    
    # 🔀 REDIRECTION CHRONOLOGIQUE PAR RÔLE
    if role in ['administrateur', 'admin', 'gérant', 'directeur']:
        return redirect(url_for('accueil_admin'))
    elif role in ['caissier', 'caisse']:
        return redirect(url_for('accueil_caissier'))
    elif role in ['ouvrier', 'technicien', 'élevage']:
        return redirect(url_for('accueil_ouvrier'))
    else:
        # Rôle par défaut si non spécifié ou inconnu
        return redirect(url_for('accueil_ouvrier'))

# -----------------------------------------------------------------
# ACCUEIL 1 : COMPTE DIRECTION / ADMINISTRATEUR
# -----------------------------------------------------------------
@app.route('/accueil_admin')
def accueil_admin():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    utilisateur = Users.query.get(session['user_id'])
    if not utilisateur or utilisateur.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur']:
        flash("❌ Accès refusé. Cette zone nécessite des privilèges d'administration.", "error")
        return redirect(url_for('index'))
        
    try:
        config = Configuration.query.first()
        code_actuel = config.cle_invitation if (config and config.cle_invitation) else "Aucun (Inscriptions verrouillées)"
    except Exception:
        code_actuel = "Erreur de configuration"
        
    return render_template('accueil.html', code_secret=code_actuel)

# -----------------------------------------------------------------
# ACCUEIL 2 : COMPTE COMMERCIAL / CAISSIER
# -----------------------------------------------------------------
@app.route('/accueil_caissier')
def accueil_caissier():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    utilisateur = Users.query.get(session['user_id'])
    if not utilisateur or utilisateur.Fonction.lower().strip() not in ['caissier', 'caisse', 'caissière']:
        flash("❌ Accès restreint au personnel de caisse.", "error")
        return redirect(url_for('index'))
        
    return render_template('caissier.html')

# -----------------------------------------------------------------
# ACCUEIL 3 : COMPTE TECHNIQUE / OUVRIER VACHER / AVICOLE
# -----------------------------------------------------------------
@app.route('/accueil_ouvrier')
def accueil_ouvrier():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    utilisateur = Users.query.get(session['user_id'])
    if not utilisateur or utilisateur.Fonction.lower().strip() not in ['ouvrier', 'technicien', 'élevage', 'ouvrier avicole']:
        flash("❌ Accès restreint au personnel technique d'élevage.", "error")
        return redirect(url_for('index'))
        
    return render_template('ouvrier.html')

@app.route('/connexion', methods=['GET'])
def connexion_get():
    try:
        total_utilisateurs = Users.query.count()
        config = Configuration.query.first()
        autoriser_inscription = (total_utilisateurs == 0 or (config and config.cle_invitation))
    except Exception:
        autoriser_inscription = True
    return render_template('login.html', code_disponible=autoriser_inscription)


@app.route('/connexion', methods=['POST'])
def connexion_post():
    username = request.form.get('NomUtilisateur')
    password = request.form.get('MotPasse')
    user = Users.query.filter_by(NomUtilisateur=username).first()
    
    if user and check_password_hash(user.MotPasse, password):
        # 🔒 VÉRIFICATION DU BLOCAGE SUPER-ADMIN
        if hasattr(user, 'EstActif') and not user.EstActif:
            flash("❌ Accès Refusé : Votre compte a été suspendu par le premier administrateur.", "error")
            return redirect(url_for('connexion_get'))
            
        session['user_id'] = user.NumUser
        session['username'] = user.NomUtilisateur
        return redirect(url_for('index'))
    else:
        flash("Nom d'utilisateur ou mot de passe incorrect.", "error")
        return redirect(url_for('connexion_get'))

@app.route('/deconnexion')
def deconnexion():
    session.clear()
    flash("Vous avez été déconnecté.", "success")
    return redirect(url_for('connexion_get'))

@app.route('/maj_code_secret', methods=['POST'])
def maj_code_secret():
    # 🔒 BARRIÈRE INFRANCHISSABLE : Strictement réservé à l'ID fondateur 1
    if session.get('user_id') != 1:
        flash("❌ Accès interdit : Seul le premier administrateur fondateur peut modifier la clé d'accès.", "error")
        return redirect(url_for('index'))
        
    nouveau_code = request.form.get('NouveauCode').strip()
    config = Configuration.query.first()
    if not config:
        config = Configuration(cle_invitation=nouveau_code)
        db.session.add(config)
    else:
        config.cle_invitation = nouveau_code if nouveau_code != "" else None
        
    db.session.commit()
    flash("✔ Clé d'inscription mise à jour avec succès !", "success")
    return redirect(url_for('accueil_admin'))

@app.route('/inscription', methods=['GET'])
def formulaire_inscription():
    total_utilisateurs = Users.query.count()
    config = Configuration.query.first()
    if total_utilisateurs > 0 and (not config or not config.cle_invitation):
        flash("Les inscriptions sont fermées.", "error")
        return redirect(url_for('connexion_get'))
    return render_template('USER.html', premier_chargement=(total_utilisateurs == 0))


# -----------------------------------------------------------------
# INTERFACE DE CAPTURE ET MANAGEMENT DES COMPTES (SUPER-ADMIN)
# -----------------------------------------------------------------

# 🔒 CONSOLE GENERALE : AFFICHAGE COMPTES + HISTORIQUE DE TRACABILITÉ
@app.route('/superadmin/utilisateurs')
def gestion_comptes_superadmin():
    if session.get('user_id') != 1:
        flash("❌ Accès strictement interdit.", "error")
        return redirect(url_for('index'))
        
    tous_les_utilisateurs = Users.query.filter(Users.NumUser != 1).order_by(Users.NomUtilisateur.asc()).all()
    
    # Extraction des 30 derniers événements de sécurité pour traçabilité visuelle
    historique_actions = JournalSecurite.query.order_by(JournalSecurite.date_action.desc()).limit(30).all()
    
    return render_template(
        'superadmin_comptes.html', 
        utilisateurs=tous_les_utilisateurs, 
        journaux=historique_actions
    )

# 🔐 ACTION 1 : MODIFICATION DE MOT DE PASSE + TRACABILITÉ
@app.route('/superadmin/modifier_passe/<int:num_user>', methods=['POST'])
def superadmin_modifier_passe(num_user):
    if session.get('user_id') != 1:
        flash("❌ Action non autorisée.", "error")
        return redirect(url_for('index'))
        
    nouveau_passe = request.form.get('NouveauMotPasse')
    if not nouveau_passe or nouveau_passe.strip() == "":
        flash("❌ Le mot de passe ne peut pas être vide.", "error")
        return redirect(url_for('gestion_comptes_superadmin'))
        
    user = Users.query.get(num_user)
    if user:
        user.MotPasse = generate_password_hash(nouveau_passe.strip())
        
        # 📝 Enregistrement dans le journal d'audit
        log = JournalSecurite(
            action_menee="MOT DE PASSE CHANGÉ",
            details=f"Le mot de passe de l'utilisateur @{user.NomUtilisateur} (ID: {user.NumUser}) a été réinitialisé de force.",
            id_cible=user.NumUser
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f"✔ Le mot de passe de @{user.NomUtilisateur} a été modifié et tracé.", "success")
        
    return redirect(url_for('gestion_comptes_superadmin'))

# 🚫 ACTION 2 : BASCULEMENT D'ACCÈS + TRACABILITÉ
@app.route('/superadmin/basculer_acces/<int:num_user>')
def superadmin_basculer_acces(num_user):
    if session.get('user_id') != 1:
        flash("❌ Action non autorisée.", "error")
        return redirect(url_for('index'))
        
    user = Users.query.get(num_user)
    if user:
        user.EstActif = not user.EstActif
        type_action = "DEBLOCAGE" if user.EstActif else "BLOCAGE"
        description = f"L'accès à l'ERP pour @{user.NomUtilisateur} a été " + ("rétabli." if user.EstActif else "suspendu.")
        
        # 📝 Enregistrement dans le journal d'audit
        log = JournalSecurite(
            action_menee=type_action,
            details=description,
            id_cible=user.NumUser
        )
        db.session.add(log)
        db.session.commit()
        
        statut_texte = "autorisé" if user.EstActif else "banni"
        flash(f"✔ Statut de @{user.NomUtilisateur} mis à jour ({statut_texte}) et mémorisé dans le journal.", "success")
        
    return redirect(url_for('gestion_comptes_superadmin'))

@app.route('/ajouter_utilisateur', methods=['POST'])
def ajouter_utilisateur():
    username = request.form.get('NomUtilisateur')
    password = request.form.get('MotPasse')
    fonction = request.form.get('Fonction', 'Caissier')
    adresse = request.form.get('Adresse')
    telephone = request.form.get('Telephone')
    code_fourni = request.form.get('CodeInvitation')
    
    if not all([username, password, adresse, telephone]):
        flash("Champs obligatoires manquants !", "error")
        return redirect(url_for('formulaire_inscription'))
    try:
        total_utilisateurs = Users.query.count()
        config = Configuration.query.first()
        if total_utilisateurs > 0:
            if not config or code_fourni != config.cle_invitation:
                flash("Code d'invitation incorrect.", "error")
                return redirect(url_for('formulaire_inscription'))
        user_existant = Users.query.filter_by(NomUtilisateur=username).first()
        if user_existant:
            flash("Nom d'utilisateur déjà pris.", "error")
            return redirect(url_for('formulaire_inscription'))
            
        nouvel_utilisateur = Users(
            NomUtilisateur=username,
            MotPasse=generate_password_hash(password),
            Fonction=fonction,
            Adresse=adresse,
            Telephone=telephone
        )
        db.session.add(nouvel_utilisateur)
        if total_utilisateurs > 0 and config:
            config.cle_invitation = None
        db.session.commit()
        return redirect(url_for('connexion_get'))
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur : {e}", "error")
        return redirect(url_for('formulaire_inscription'))


# --- CONFIGURATION DE L'ENTREPRISE (EN-TÊTES FACTURES) ---

@app.route('/modifier_configuration', methods=['GET', 'POST'])
def modifier_configuration():
    # 1. SÉCURITÉ : Vérification de la connexion de l'utilisateur
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # 2. ACCÈS EXCLUSIF : Validation stricte de l'identité de l'administrateur
        user_connecte = Users.query.get(session['user_id'])
        if not user_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        # Barrière 1 : Si ce n'est pas le premier administrateur (ID 1), accès interdit
        if user_connecte.NumUser != 1:
            flash("❌ Accès interdit : La configuration des données d'exploitation est exclusive au premier administrateur.", "error")
            return redirect(url_for('index'))
            
        # Barrière 2 : Si le compte du super-admin est marqué comme désactivé
        if hasattr(user_connecte, 'EstActif') and not user_connecte.EstActif:
            flash("❌ Accès Refusé : Votre compte super-administratif est désactivé.", "error")
            return redirect(url_for('deconnexion'))

        # Extraction de la configuration existante
        config = Configuration.query.first()

        # =================================================================
        # TRITEMENT DU FORMULAIRE (MÉTHODE POST)
        # =================================================================
        if request.method == 'POST':
            raison_sociale = request.form.get('raison_sociale', '').strip()
            adresse = request.form.get('adresse', '').strip()
            telephone = request.form.get('telephone', '').strip()
            email = request.form.get('email', '').strip()
            ninea = request.form.get('ninea', '').strip()
            rccm = request.form.get('rccm', '').strip()
            
            # Gestion du téléversement du logo officiel
            file = request.files.get('logo')
            logo_filename = config.logo if config else None
            
            if file and file.filename != '':
                if allowed_file(file.filename):
                    if not os.path.exists(UPLOAD_FOLDER):
                        os.makedirs(UPLOAD_FOLDER)
                    # Sécurisation du nom de fichier pour éviter les injections de chemin
                    filename = secure_filename(f"logo_promas_{secure_filename(file.filename)}")
                    file.save(os.path.join(UPLOAD_FOLDER, filename))
                    logo_filename = os.path.join(UPLOAD_FOLDER, filename)
                else:
                    flash("❌ Format de fichier non supporté pour le logo (Extensions autorisées : PNG, JPG, JPEG, GIF).", "error")
                    return render_template('modifier_configuration.html', config=config)

            # Si aucune configuration n'existe en base, on crée la première ligne
            if not config:
                config = Configuration(
                    raison_sociale=raison_sociale,
                    adresse=adresse,
                    telephone=telephone,
                    email=email,
                    ninea=ninea,
                    rccm=rccm,
                    logo=logo_filename
                )
                db.session.add(config)
                # 📝 Log d'audit pour le suivi de traçabilité créé précédemment
                if 'JournalSecurite' in globals():
                    log = JournalSecurite(
                        action_menee="CONFIGURATION INITIALISÉE",
                        details=f"Le Super-Admin a configuré initialement les données d'en-tête de l'entreprise : {raison_sociale}.",
                        id_cible=user_connecte.NumUser
                    )
                    db.session.add(log)
            else:
                # Sinon, on applique les modifications sur la ligne existante
                config.raison_sociale = raison_sociale
                config.adresse = adresse
                config.telephone = telephone
                config.email = email
                config.ninea = ninea
                config.rccm = rccm
                config.logo = logo_filename
                
                if 'JournalSecurite' in globals():
                    log = JournalSecurite(
                        action_menee="CONFIGURATION MODIFIÉE",
                        details="Le Super-Admin a mis à jour les coordonnées et paramètres d'en-tête officiels de l'entreprise.",
                        id_cible=user_connecte.NumUser
                    )
                    db.session.add(log)

            db.session.commit()
            flash("✔ Paramètres d'en-tête de l'entreprise mis à jour avec succès !", "success")
            return redirect(url_for('accueil_admin'))

        # =================================================================
        # RENDU VISUEL DE LA PAGE (MÉTHODE GET)
        # =================================================================
        return render_template('configuration.html', config=config)

    except Exception as e:
        db.session.rollback()
        return f"<h3>❌ Erreur lors du traitement de la configuration :</h3> <p>{str(e)}</p>"


# --- MODULE LOTS AVICOLES (AVEC MODIFICATION ET SELECTION DE FERME) ---
@app.route('/lots', methods=['GET'])
def liste_lots():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    # 1. AUTHENTIFICATION & ROLES STRICTS
    utilisateur_connecte = db.session.get(Users, session['user_id'])
    if not utilisateur_connecte:
        session.clear()
        return redirect(url_for('connexion_get'))
        
    # Nettoyage textuel de la fonction
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    
    # Définition des deux seuls groupes autorisés
    roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    roles_terrain = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']
    
    est_admin = fonction_user in roles_superieurs
    est_ouvrier = fonction_user in roles_terrain

    # ❌ BLOCAGE DE SÉCURITÉ : Si l'utilisateur n'est ni Admin ni Ouvrier
    if not est_admin and not est_ouvrier:
        flash("Accès refusé : Privilèges insuffisants pour administrer les fiches tiers.", "error")
        return redirect(url_for('index'))

    # 2. CONFIGURATION DE LA PAGINATION NATIVE (RENDU ULTRA-RAPIDE)
    page = request.args.get('page', 1, type=int)
    par_page = 25  # Nombre de lots par page

    query_lots = LotAvicole.query

    # 3. APPLICATION DU CLOISONNEMENT STRICT POUR LES OUVRIERS
    if est_ouvrier:
        # L'ouvrier agricole accède STRICTEMENT à ses propres enregistrements
        query_lots = query_lots.filter(LotAvicole.id_user == session['user_id'])
        
    # Exécution de la requête paginée
    pagination = query_lots.order_by(LotAvicole.date_arrivee.desc()).paginate(
        page=page, per_page=par_page, error_out=False
    )

    # 4. EXTRACTION DES FERMES POUR LE FILTRE HTML (SANS CHARGER TOUTE LA BDD)
    if est_admin:
        fermes_brutes = db.session.query(LotAvicole.souche).distinct().all()
    else:
        fermes_brutes = db.session.query(LotAvicole.souche).filter(LotAvicole.id_user == session['user_id']).distinct().all()

    fermes_uniques = set()
    for row in fermes_brutes:
        if row and row[0]:
            raw_details = row[0]
            if "Ferme : " in raw_details:
                ferme = raw_details.replace("Ferme : ", "").strip()
            elif " (" in raw_details and ")" in raw_details:
                ferme = raw_details.split(" (")[1].replace(")", "").strip()
            else:
                ferme = raw_details.strip()
            if ferme:
                fermes_uniques.add(ferme)

    # 5. RENDU DU TEMPLATE AVEC LES DONNÉES SÉCURISÉES
    return render_template(
        'lot_avicole.html', 
        lots=pagination.items, 
        pagination=pagination, 
        est_admin=est_admin,
        liste_fermes_filtre=sorted(list(fermes_uniques))
    )

@app.route('/lots/ajouter', methods=['POST'])
def ajouter_lot():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    # 1. AUTHENTIFICATION & VÉRIFICATION DES RÔLES STRICTS
    utilisateur_connecte = db.session.get(Users, session['user_id'])
    if not utilisateur_connecte:
        session.clear()
        return redirect(url_for('connexion_get'))
        
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    
    # Définition des deux seuls groupes autorisés
    roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    roles_terrain = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']
    
    est_admin = fonction_user in roles_superieurs
    est_ouvrier = fonction_user in roles_terrain

    # ❌ BLOCAGE DE SÉCURITÉ : Si l'utilisateur n'est ni Admin ni Ouvrier
    if not est_admin and not est_ouvrier:
        flash("Accès refusé : Privilèges insuffisants pour administrer les fiches tiers.", "error")
        return redirect(url_for('index'))

    # 2. RÉCUPÉRATION DES DONNÉES DU FORMULAIRE
    id_lot_modif = request.form.get('id_lot_modif')
    nom_ferme = request.form.get('nom_ferme', '').strip()
    type_elevage = request.form.get('type_elevage')
    souche = request.form.get('souche', '').strip()
    date_arrivee_str = request.form.get('date_arrivee')
    effectif_initial = request.form.get('effectif_initial')

    if not all([nom_ferme, type_elevage, date_arrivee_str, effectif_initial]):
        flash("Veuillez remplir tous les champs obligatoires (*).", "error")
        return redirect(url_for('liste_lots'))

    try:
        date_arrivee = datetime.strptime(date_arrivee_str, '%Y-%m-%d').date()
        
        # -----------------------------------------------------------------
        # CAS 1 : MODIFICATION D'UN LOT EXISTANT
        # -----------------------------------------------------------------
        if id_lot_modif:
            lot = LotAvicole.query.get(int(id_lot_modif))
            if lot:
                # 🔒 SÉCURITÉ : Bloque la modification si l'utilisateur est ouvrier mais n'est pas l'auteur initial
                if est_ouvrier and hasattr(lot, 'id_user') and lot.id_user != session['user_id']:
                    flash("❌ Action refusée : Vous n'êtes pas autorisé à modifier un lot enregistré par un autre agent.", "error")
                    return redirect(url_for('liste_lots'))
                
                # Mise à jour des données
                lot.type_elevage = type_elevage
                lot.souche = f"{souche} ({nom_ferme})" if souche else f"Ferme : {nom_ferme}"
                lot.date_arrivee = date_arrivee
                lot.effectif_initial = int(effectif_initial)
                
                db.session.commit()
                flash(f"Le lot {lot.code_lot} a été modifié avec succès !", "success")
                return redirect(url_for('liste_lots'))
                
        # -----------------------------------------------------------------
        # CAS 2 : CRÉATION D'UN NOUVEAU LOT DYNAMIQUE
        # -----------------------------------------------------------------
        else:
            annee_actuelle = date_arrivee.year
            prefixe = "PL" if type_elevage == "Poules Pondeuses" else "PC"
            recherche_pattern = f"{prefixe}-{annee_actuelle}-%"
            
            nb_lots_annee = LotAvicole.query.filter(LotAvicole.code_lot.like(recherche_pattern)).count()
            prochain_numero = nb_lots_annee + 1
            code_lot_auto = f"{prefixe}-{annee_actuelle}-{prochain_numero:03d}"
            
            nouveau_lot = LotAvicole(
                code_lot=code_lot_auto,
                type_elevage=type_elevage,
                souche=f"{souche} ({nom_ferme})" if souche else f"Ferme : {nom_ferme}",
                date_arrivee=date_arrivee,
                effectif_initial=int(effectif_initial),
                id_user=session['user_id'] # Traçabilité immédiate de l'auteur de l'enregistrement
            )
            
            db.session.add(nouveau_lot)
            db.session.commit()
            flash(f"Lot enregistré à la {nom_ferme} ! Code unique : {code_lot_auto}", "success")
            return redirect(url_for('liste_lots'))

    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors du traitement du lot : {str(e)}", "error")
        return redirect(url_for('liste_lots'))

# =======================================================================
# MODULE FOURNISSEURS (SÉCURISÉ & OPTIMISÉ POUR LE FUTUR)
# =======================================================================

@app.route('/fournisseurs', methods=['GET'])
def liste_fournisseurs():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # 1. SÉCURITÉ : Audit du rôle utilisateur
        utilisateur_connecte = Users.query.get(session['user_id'])
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        roles_autorises = roles_superieurs + ['caissier', 'caissière']
        
        if fonction_user not in roles_autorises:
            flash("Accès refusé : Privilèges insuffisants pour administrer les fiches tiers.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs

        recherche = request.args.get('search_nom', '').strip()
        page = request.args.get('page', 1, type=int)
        par_page = 40  # Seuil de fluidité par écran

        # 2. OPTIMISATION : Requête de filtrage avec joinedload
        query_fournisseurs = Fournisseur.query.options(joinedload(Fournisseur.user))
        
        if recherche:
            query_fournisseurs = query_fournisseurs.filter(
                or_(
                    Fournisseur.nom.ilike(f'%{recherche}%'),
                    Fournisseur.telephone.ilike(f'%{recherche}%')
                )
            )
            
        # CLOISONNEMENT VISUEL STRICT : Le caissier ne liste QUE ses propres fournisseurs
        if not est_admin_ou_comptable:
            query_fournisseurs = query_fournisseurs.filter(Fournisseur.id_user == session['user_id'])
            
        # 3. LÉGÈRETÉ : Extraction paginée native
        pagination = query_fournisseurs.order_by(Fournisseur.nom.asc()).paginate(
            page=page, per_page=par_page, error_out=False
        )
        
        return render_template(
            'fournisseur.html', 
            fournisseurs=pagination.items,
            pagination=pagination,
            search_val=recherche,
            est_admin=est_admin_ou_comptable
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'accès au module fournisseurs : {str(e)}", "error")
        return redirect(url_for('index'))


@app.route('/fournisseurs/ajouter', methods=['POST'])
def ajouter_fournisseur():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # SÉCURITÉ : Blocage de soumission forcée par un rôle non autorisé
        id_operateur = session['user_id']
        utilisateur_connecte = Users.query.get(id_operateur)
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        roles_autorises = roles_superieurs + ['caissier', 'caissière']
        
        if fonction_user not in roles_autorises:
            flash("Action interdite : Droits insuffisants.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs

        id_fournisseur_modif = request.form.get('id_fournisseur_modif')
        nom = request.form.get('nom', '').strip()
        telephone = request.form.get('telephone', '').strip()
        adresse = request.form.get('adresse', '').strip()
        
        if not all([nom, telephone]):
            flash("Veuillez remplir tous les champs obligatoires (*).", "error")
            return redirect(url_for('liste_fournisseurs'))
            
        # CAS 1 : MODIFICATION D'UN FOURNISSEUR EXISTANT
        if id_fournisseur_modif:
            fournisseur = Fournisseur.query.get(int(id_fournisseur_modif))
            if not fournisseur:
                flash("Fournisseur introuvable pour la modification.", "error")
                return redirect(url_for('liste_fournisseurs'))
                
            # PROTECTION ANTI-FRAUDE : Le caissier ne peut modifier que ses propres fiches
            if not est_admin_ou_comptable and fournisseur.id_user != id_operateur:
                flash("Action interdite : Vous n'êtes pas l'auteur de cette fiche tiers.", "error")
                return redirect(url_for('liste_fournisseurs'))
                
            fournisseur.nom = nom
            fournisseur.telephone = telephone
            fournisseur.adresse = adresse if adresse else None
            db.session.commit()
            flash(f"✔ La fiche du fournisseur '{nom}' a été modifiée avec succès !", "success")
                
        # CAS 2 : ENREGISTREMENT D'UN NOUVEAU FOURNISSEUR AUTOMATISÉ
        else:
            nouveau_fournisseur = Fournisseur(
                nom=nom,
                telephone=telephone,
                adresse=adresse if adresse else None,
                id_user=id_operateur  # Attribution automatique invisible et inviolable
            )
            db.session.add(nouveau_fournisseur)
            db.session.commit()
            flash(f"✔ Le fournisseur '{nom}' a été enregistré avec succès !", "success")
            
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors du traitement de la fiche fournisseur : {str(e)}", "error")
        
    return redirect(url_for('liste_fournisseurs'))

# =======================================================================
# MODULE CLIENTS (CLOISONNÉ, SÉCURISÉ & AFFICHAGE FLASH PAGINÉ)
# =======================================================================

@app.route('/clients', methods=['GET'])
def liste_clients():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # 1. SÉCURITÉ : Audit du rôle utilisateur
        utilisateur_connecte = Users.query.get(session['user_id'])
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        roles_autorises = roles_superieurs + ['caissier', 'caissière']
        
        if fonction_user not in roles_autorises:
            flash("Accès refusé : Privilèges insuffisants pour consulter le fichier clients.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs

        recherche = request.args.get('search_nom', '').strip()
        page = request.args.get('page', 1, type=int)
        par_page = 40  # Seuil de fluidité par écran

        # 2. OPTIMISATION : Requête de filtrage native avec joinedload (Évite le problème N+1)
        query_clients = Client.query.options(joinedload(Client.user))
        
        if recherche:
            query_clients = query_clients.filter(
                or_(
                    Client.nom.ilike(f'%{recherche}%'),
                    Client.telephone.ilike(f'%{recherche}%')
                )
            )
            
        # CLOISONNEMENT VISUEL STRICT : Le caissier ne liste QUE ses propres clients
        if not est_admin_ou_comptable:
            query_clients = query_clients.filter(Client.id_user == session['user_id'])
            
        # 3. LÉGÈRETÉ : Extraction paginée native SQL
        pagination = query_clients.order_by(Client.nom.asc()).paginate(
            page=page, per_page=par_page, error_out=False
        )
        
        return render_template(
            'client.html', 
            clients=pagination.items,
            pagination=pagination,
            search_val=recherche,
            est_admin=est_admin_ou_comptable
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'accès au module clients : {str(e)}", "error")
        return redirect(url_for('index'))


@app.route('/clients/ajouter', methods=['POST'])
def ajouter_client():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # SÉCURITÉ : Blocage de soumission forcée par un rôle non autorisé
        id_operateur = session['user_id']
        utilisateur_connecte = Users.query.get(id_operateur)
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        roles_autorises = roles_superieurs + ['caissier', 'caissière']
        
        if fonction_user not in roles_autorises:
            flash("Action interdite : Droits insuffisants.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs

        id_client_modif = request.form.get('id_client_modif')
        nom = request.form.get('nom', '').strip()
        telephone = request.form.get('telephone', '').strip()
        adresse = request.form.get('adresse', '').strip()
        
        if not all([nom, telephone]):
            flash("Veuillez remplir tous les champs obligatoires (*).", "error")
            return redirect(url_for('liste_clients'))
            
        # CAS 1 : MODIFICATION D'UN CLIENT EXISTANT
        if id_client_modif:
            client = Client.query.get(int(id_client_modif))
            if not client:
                flash("Client introuvable pour la modification.", "error")
                return redirect(url_for('liste_clients'))
                
            # PROTECTION ANTI-FRAUDE : Le caissier ne peut modifier que ses propres fiches
            if not est_admin_ou_comptable and client.id_user != id_operateur:
                flash("Action interdite : Vous n'êtes pas l'auteur de cette fiche client.", "error")
                return redirect(url_for('liste_clients'))
                
            client.nom = nom
            client.telephone = telephone
            client.adresse = adresse if adresse else None
            db.session.commit()
            flash(f"✔ La fiche du client '{nom}' a été modifiée avec succès !", "success")
                
        # CAS 2 : ENREGISTREMENT D'UN NOUVEAU CLIENT AUTOMATISÉ
        else:
            nouveau_client = Client(
                nom=nom,
                telephone=telephone,
                adresse=adresse if adresse else None,
                id_user=id_operateur  # Attribution automatique invisible et inviolable
            )
            db.session.add(nouveau_client)
            db.session.commit()
            flash(f"✔ Le client '{nom}' a été enregistré avec succès !", "success")
            
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors du traitement de la fiche client : {str(e)}", "error")
        
    return redirect(url_for('liste_clients'))

@app.route('/mortalites', methods=['GET'])
def liste_mortalites():
    # Vérification de la session utilisateur
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    
    # 1. Identification de l'utilisateur et validation des droits
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte or not utilisateur_connecte.Fonction:
        return redirect(url_for('connexion_get'))
        
    # Alignement strict sur la nomenclature de vos rôles
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    roles_ouvrier = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']

    # Sécurité globale d'accès à la page
    if fonction_user not in roles_admin and fonction_user not in roles_ouvrier:
        flash("❌ Accès refusé : Votre profil ne vous permet pas de consulter le registre sanitaire.", "error")
        return redirect(url_for('index'))

    # Détermination du niveau d'accès (Privilèges d'administration vs Employé cloisonné)
    est_admin = fonction_user in roles_admin
    infos_entreprise = Configuration.query.first()
    
    # Configuration de la pagination native SQLAlchemy (Affichage ultra-rapide)
    page = request.args.get('page', 1, type=int)
    par_page = 20  # Limite fixe par page pour garantir la rapidité de chargement
    
    # 2. Cloisonnement applicatif de la base de données
    if est_admin:
        # Les administrateurs / directeurs / comptables voient l'intégralité de l'exploitation
        lots_disponibles = LotAvicole.query.all()
        query_mortalites = Mortalite.query
    else:
        # Les ouvriers / agents / techniciens ne voient que leurs lots affectés et leurs propres saisies
        lots_disponibles = LotAvicole.query.filter_by(id_user=user_id_connecte).all()
        query_mortalites = Mortalite.query.filter(Mortalite.id_user == user_id_connecte)
        
    # Exécution de la requête avec tri chronologique inverse et pagination SQL native
    pagination = query_mortalites.order_by(Mortalite.date_mortalite.desc()).paginate(
        page=page, per_page=par_page, error_out=False
    )
    registres = pagination.items

    # 3. RECHERCHE DE LA TOUTE DERNIÈRE SAISIE DE L'UTILISATEUR (Pour pré-sélection du lot)
    derniere_saisie = Mortalite.query.filter_by(id_user=user_id_connecte)\
                                     .order_by(Mortalite.id_mortalite.desc())\
                                     .first()
    
    # ID du lot par défaut (chaîne vide si aucune saisie n'a encore été effectuée)
    dernier_id_lot = derniere_saisie.id_lot if derniere_saisie else ""

    # 4. Injection dynamique et calcul du taux de mortalité cumulé sur la page active
    for r in registres:
        total_pertes_lot = db.session.query(func.sum(Mortalite.nombre)).filter(
            Mortalite.id_lot == r.id_lot,
            Mortalite.date_mortalite <= r.date_mortalite
        ).scalar() or 0
        
        if r.lot_avicole and r.lot_avicole.effectif_initial > 0:
            r.taux_cumule = (total_pertes_lot / r.lot_avicole.effectif_initial) * 100
        else:
            r.taux_cumule = 0.0

    return render_template(
        'mortalite.html', 
        lots=lots_disponibles, 
        registres=registres,
        pagination=pagination, 
        est_admin=est_admin, 
        entreprise=infos_entreprise,
        dernier_id_lot=dernier_id_lot  # Transmis au template pour initialiser le filtre JS
    )

@app.route('/mortalites/ajouter', methods=['POST'])
def ajouter_mortalite():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte or not utilisateur_connecte.Fonction:
        return redirect(url_for('connexion_get'))
        
    # Alignement strict sur la nomenclature de vos rôles
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    roles_ouvrier = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']
    
    if fonction_user not in roles_admin and fonction_user not in roles_ouvrier:
        flash("❌ Action refusée : Droits insuffisants.", "error")
        return redirect(url_for('liste_mortalites'))
        
    est_admin = fonction_user in roles_admin
    
    id_mortalite_modif = request.form.get('id_mortalite_modif')
    id_lot = request.form.get('id_lot')
    date_mortalite_str = request.form.get('date_mortalite')
    nombre = request.form.get('nombre')
    cause = request.form.get('cause', '').strip()
    
    if not all([id_lot, date_mortalite_str, nombre]):
        flash("Veuillez remplir tous les champs obligatoires (*).", "error")
        return redirect(url_for('liste_mortalites'))
        
    try:
        id_lot_int = int(id_lot)
        
        # Récupération du lot cible
        lot_cible = LotAvicole.query.get(id_lot_int)
        if not lot_cible:
            flash("❌ Erreur : Le lot sélectionné n'existe pas.", "error")
            return redirect(url_for('liste_mortalites'))

        # SÉCURITÉ ACCÈS LOT : Cloisonnement strict des ouvriers
        if not est_admin and lot_cible.id_user != user_id_connecte:
            flash("❌ Enregistrement refusé : Vous n'êtes pas responsable de ce lot.", "error")
            return redirect(url_for('liste_mortalites'))
                
        # Conversion stricte de la chaîne HTML "YYYY-MM-DD" en objet date pure de Python
        date_mortalite = datetime.strptime(date_mortalite_str, '%Y-%m-%d').date()
        date_aujourdhui = date.today()
        
        # 1. CONTRAINTES TEMPORELLES DE SÉCURITÉ
        # Règle A : Interdire les saisies dans le futur
        if date_mortalite > date_aujourdhui:
            flash("❌ Saisie invalide : Impossible d'enregistrer une mortalité dans le futur.", "error")
            return redirect(url_for('liste_mortalites'))
            
        # Règle B : Interdire les dates antérieures à la création du lot
        date_creation_lot = None
        if hasattr(lot_cible, 'date_creation') and lot_cible.date_creation:
            date_creation_lot = lot_cible.date_creation
        elif hasattr(lot_cible, 'date_mise_en_place') and lot_cible.date_mise_en_place:
            date_creation_lot = lot_cible.date_mise_en_place

        if date_creation_lot:
            if isinstance(date_creation_lot, datetime):
                date_creation_lot = date_creation_lot.date()
            if date_mortalite < date_creation_lot:
                flash(f"❌ Saisie invalide : La date du constat ne peut pas être antérieure à la création du lot ({date_creation_lot.strftime('%d/%m/%Y')}).", "error")
                return redirect(url_for('liste_mortalites'))

        # =================================================================
        # VERROUILLAGE IMPLIQUANT LE NETTOYAGE DU CACHE DE PERSISTANCE
        # =================================================================
        # Étape cruciale : On vide le cache de session pour forcer l'analyse de la BDD réelle
        db.session.expire_all() 
        
        # CAS 1 : EN COURS DE MODIFICATION D'UNE FICHE
        if id_mortalite_modif and id_mortalite_modif.strip() != "":
            id_modif_int = int(id_mortalite_modif)
            morte = Mortalite.query.get(id_modif_int)
            
            if morte:
                if not est_admin and morte.id_user != user_id_connecte:
                    flash("❌ Action interdite : Vous ne pouvez pas modifier cette fiche.", "error")
                    return redirect(url_for('liste_mortalites'))
                
                # Vérifie si une AUTRE ligne possède déjà cette même date pour ce lot
                deja_existant = Mortalite.query.filter(
                    Mortalite.id_lot == id_lot_int,
                    Mortalite.date_mortalite == date_mortalite,
                    Mortalite.id_mortalite != id_modif_int
                ).first()
                
                if deja_existant:
                    flash(f"❌ Enregistrement impossible : Une déclaration de mortalité existe déjà pour le lot {lot_cible.code_lot} à la date du {date_mortalite.strftime('%d/%m/%Y')}. Veuillez modifier la fiche existante.", "error")
                    return redirect(url_for('liste_mortalites'))
                    
                morte.id_lot = id_lot_int
                morte.date_mortalite = date_mortalite
                morte.nombre = int(nombre)
                morte.cause = cause if cause else None
                db.session.commit()
                flash("Fiche de mortalité mise à jour avec succès.", "success")
                
        # CAS 2 : NOUVEL ENREGISTREMENT (AJOUT)
        else:
            # Interrogation de la base de données sur le couple unique (id_lot, date_mortalite)
            deja_existant = Mortalite.query.filter(
                Mortalite.id_lot == id_lot_int,
                Mortalite.date_mortalite == date_mortalite
            ).first()
            
            if deja_existant:
                flash(f"❌ Saisie refusée : Ce lot ({lot_cible.code_lot}) possède déjà un enregistrement de pertes pour la journée du {date_mortalite.strftime('%d/%m/%Y')}. Il est interdit d'ajouter des doublons.", "error")
                return redirect(url_for('liste_mortalites'))
            
            # Création avec liaison conforme à votre clé étrangère 'users.NumUser'
            nouvelle_perte = Mortalite(
                id_lot=id_lot_int,
                date_mortalite=date_mortalite,
                nombre=int(nombre),
                cause=cause if cause else None,
                id_user=user_id_connecte # Mappe correctement vers users.NumUser via l'ORM
            )
            db.session.add(nouvelle_perte)
            db.session.commit()
            flash("Déclaration de mortalité enregistrée au registre avec succès.", "success")
            
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'écriture dans le registre sanitaire : {e}", "error")
        
    return redirect(url_for('liste_mortalites'))

# ==============================================================================
# MODULE ALIMENTATION (CORRECTIF SÉCURISÉ MULTI-ANNÉES POUR SQLITE)
# ==============================================================================

@app.route('/alimentation', methods=['GET'])
@app.route('/alimentations', methods=['GET'])
def liste_alimentations():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    # -----------------------------------------------------------------
    # 1. AUTHENTIFICATION & ROLES STRICTS
    # -----------------------------------------------------------------
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte:
        session.clear()
        return redirect(url_for('connexion_get'))
        
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    roles_ouvrier = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']
    
    est_admin = fonction_user in roles_admin
    est_ouvrier = fonction_user in roles_ouvrier

    if not est_admin and not est_ouvrier:
        flash("Accès refusé : Privilèges insuffisants pour administrer les fiches tiers.", "error")
        return redirect(url_for('index'))

    lots_disponibles = LotAvicole.query.all()
    infos_entreprise = Configuration.query.first()
    
    maintenant = datetime.now()
    annee_courante = str(maintenant.year)
    mois_courant = f"{maintenant.month:02d}"
    
    annee_selectionnee = request.args.get('annee', annee_courante)
    mois_selectionne = request.args.get('mois', mois_courant)
    lot_selectionne = request.args.get('lot', '')
    
    page = request.args.get('page', 1, type=int) 
    par_page = 20  

    # -----------------------------------------------------------------
    # 2. SELECTION ET FILTRAGE DU REGISTRE (CORRECTION TYPE DUBLON)
    # -----------------------------------------------------------------
    query_base = Alimentation.query.options(
        joinedload(Alimentation.lot_avicole),
        joinedload(Alimentation.operateur)
    )
    if est_ouvrier:
        query_base = query_base.filter(Alimentation.id_user == user_id_connecte)

    # Extraction des années : extraction explicite du premier élément du tuple (row[0])
    if est_admin:
        annees_brutes = db.session.query(extract('year', Alimentation.date_alimentation).label('annee')).distinct().all()
    else:
        annees_brutes = db.session.query(extract('year', Alimentation.date_alimentation).label('annee'))\
                                  .filter(Alimentation.id_user == user_id_connecte).distinct().all()
                                  
    # FIX: r[0] convertit l'objet Row en entier brut exploitable par Python
    liste_annees = [str(int(r[0])) for r in annees_brutes if r[0] is not None]
    if annee_courante not in liste_annees:
        liste_annees.append(annee_courante)
    liste_annees.sort(reverse=True)

    # Sécurisation des arguments de filtres temporels
    try:
        annee_filtre_int = int(float(annee_selectionnee))
        mois_filtre_int = int(float(mois_selectionne))
    except (ValueError, TypeError):
        annee_filtre_int = maintenant.year
        mois_filtre_int = maintenant.month

    # Application des filtres sur la requête paginée (Ligne 1339 Corrigée)
    query_filtree = query_base.filter(
        extract('year', Alimentation.date_alimentation) == annee_filtre_int,
        extract('month', Alimentation.date_alimentation) == mois_filtre_int
    )
    
    if lot_selectionne and lot_selectionne.strip() != '':
        query_filtree = query_filtree.filter(Alimentation.id_lot == int(lot_selectionne))
        
    pagination = query_filtree.order_by(Alimentation.date_alimentation.desc()).paginate(
        page=page, per_page=par_page, error_out=False
    )
    
    registres_filtrer = pagination.items
    quantite_totale_consommee = 0.0

    # Normalisation des informations pour l'affichage du tableau central
    for f in registres_filtrer:
        lot = f.lot_avicole
        if lot:
            total_morts = db.session.query(func.sum(Mortalite.nombre)).filter_by(id_lot=lot.id_lot).scalar() or 0
            total_vendus = 0
            f.poules_vivantes_lot = lot.effectif_initial - total_morts - total_vendus
            
            if lot.nom_ferme and lot.nom_ferme.strip() != "":
                f.nom_ferme_lot = lot.nom_ferme
            elif lot.souche and "(" in lot.souche and ")" in lot.souche:
                f.nom_ferme_lot = lot.souche.split('(')[1].replace(')', '').strip()
            else:
                f.nom_ferme_lot = "Ferme Georgette BIAYE"
        else:
            f.poules_vivantes_lot = 0
            f.nom_ferme_lot = "Non spécifiée"
        quantite_totale_consommee += f.quantite or 0.0

    # Résumé de la distribution par ferme (Boîte d'en-tête verte)
    conso_query = db.session.query(LotAvicole.nom_ferme, LotAvicole.souche, func.sum(Alimentation.quantite))\
                            .join(Alimentation, LotAvicole.id_lot == Alimentation.id_lot)
    if est_ouvrier:
        conso_query = conso_query.filter(Alimentation.id_user == user_id_connecte)
        
    conso_query = conso_query.filter(
        extract('year', Alimentation.date_alimentation) == annee_filtre_int,
        extract('month', Alimentation.date_alimentation) == mois_filtre_int
    )
    if lot_selectionne and lot_selectionne.strip() != '':
        conso_query = conso_query.filter(LotAvicole.id_lot == int(lot_selectionne))
        
    conso_par_ferme = conso_query.group_by(LotAvicole.nom_ferme, LotAvicole.souche).all()
    
    dictionnaire_fermes = {}
    for row_conso in conso_par_ferme:
        ferme, souche, total = row_conso[0], row_conso[1], row_conso[2]
        nom_propre = ferme.strip() if ferme and ferme.strip() != "" else \
                     (souche.split('(')[1].replace(')', '').strip() if souche and "(" in souche else "Ferme Georgette BIAYE")
        dictionnaire_fermes[nom_propre] = dictionnaire_fermes.get(nom_propre, 0.0) + float(total)
        
    for k in dictionnaire_fermes:
        dictionnaire_fermes[k] = round(dictionnaire_fermes[k], 1)

    # -----------------------------------------------------------------
    # 3. CALCUL COMPTABLE SANS CONSTANTE ET IMMUABLE AUX CHANGEMENTS
    # -----------------------------------------------------------------
    stock_initial_admin = getattr(infos_entreprise, 'stock_initial_cycle', 2580.0)
    ration_reference_admin = getattr(infos_entreprise, 'ration_fixe_journaliere', 86.0)

    if stock_initial_admin is None: stock_initial_admin = 2580.0
    if ration_reference_admin is None: ration_reference_admin = 86.0

    # Volume total réel de la quantité consommée ce mois-ci
    quantite_consommee_ce_mois = db.session.query(func.sum(Alimentation.quantite)).filter(
        extract('year', Alimentation.date_alimentation) == annee_filtre_int,
        extract('month', Alimentation.date_alimentation) == mois_filtre_int
    ).scalar() or 0.0

    # Formule exigée : Restant en stock = Configuré par l'admin - Somme réelle consommée
    stock_restant_calcule = float(stock_initial_admin) - float(quantite_consommee_ce_mois)

    # Compte du nombre de jours réels d'activité uniques
    nb_jours_activite_distincts = db.session.query(func.count(func.distinct(Alimentation.date_alimentation))).filter(
        extract('year', Alimentation.date_alimentation) == annee_filtre_int,
        extract('month', Alimentation.date_alimentation) == mois_filtre_int
    ).scalar() or 0

    # Soustraction calendaire pure (L'autonomie reste stable à 29 jours en cas d'édition de quantité)
    jours_theoriques_cycle = 30
    jours_autonomie = max(0, jours_theoriques_cycle - nb_jours_activite_distincts)

    produit_fini_uniquement = Produit.query.filter(Produit.designation.like('%Produit fini%')).all()

    return render_template(
        'alimentation.html', 
        lots=lots_disponibles, 
        alimentations=registres_filtrer, 
        mois_actif=mois_selectionne,
        annee_active=annee_selectionnee,
        lot_actif=lot_selectionne,
        annees=liste_annees,
        entreprise=infos_entreprise,
        conso_fermes=dictionnaire_fermes,
        quantite_totale_consommee=round(quantite_consommee_ce_mois, 1),
        produits=produit_fini_uniquement,
        stock_restant_produit=round(stock_restant_calcule, 1), # Affiche 2494.0 Kg
        jours_autonomie=jours_autonomie,                       # Affiche 29 jours restants
        pagination=pagination,
        est_admin=est_admin
    )


@app.route('/alimentation/ajouter', methods=['POST'])
def ajouter_alimentation():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    
    # 1. AUTHENTIFICATION & VÉRIFICATION DES RÔLES STRICTS
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte:
        session.clear()
        return redirect(url_for('connexion_get'))
        
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    roles_ouvrier = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']
    
    est_admin = fonction_user in roles_admin
    est_ouvrier = fonction_user in roles_ouvrier

    # Rejet si l'utilisateur n'est pas autorisé
    if not est_admin and not est_ouvrier:
        flash("Accès refusé : Privilèges insuffisants pour administrer les fiches tiers.", "error")
        return redirect(url_for('liste_alimentations'))

    db.session.remove()
    
    try:
        # 2. RÉCUPÉRATION ET VALIDATION DES DONNÉES
        id_alimentation_modif = request.form.get('id_alimentation_modif')
        date_distrib_texte = request.form.get('date_alimentation') or request.form.get('date_distribution')
        quantite_brute = request.form.get('quantite')
        id_produit_brut = request.form.get('id_produit')
        id_lot_brut = request.form.get('id_lot')

        try:
            id_produit = int(id_produit_brut)
            id_lot = int(id_lot_brut)
            quantite = float(quantite_brute)
        except (ValueError, TypeError):
            flash("❌ Erreur : Données invalides (produit, lot ou quantité numériques requis).", "error")
            return redirect(url_for('liste_alimentations'))

        # ❌ SÉCURITÉ : INTERDICTION D'UNE DATE DIFFÉRENTE D'AUJOURD'HUI
        date_du_jour = datetime.now().date()
        
        if not date_distrib_texte or date_distrib_texte.strip() == "":
            date_alimentation_objet = date_du_jour
        else:
            try:
                date_alimentation_objet = datetime.strptime(date_distrib_texte, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                date_alimentation_objet = date_du_jour

        if date_alimentation_objet != date_du_jour:
            flash(f"❌ Saisie refusée : Impossible d'enregistrer une distribution pour une date différente d'aujourd'hui ({date_du_jour.strftime('%d/%m/%Y')}).", "error")
            return redirect(url_for('liste_alimentations'))

        # ❌ SÉCURITÉ : INTERDICTION DES DOUBLONS DE DATE POUR UN MÊME LOT
        fiche_doublon_existante = Alimentation.query.filter_by(
            id_lot=id_lot,
            date_alimentation=date_du_jour
        ).first()

        if fiche_doublon_existante:
            if not id_alimentation_modif or int(id_alimentation_modif) != fiche_doublon_existante.id_alimentation:
                flash(f"❌ Enregistrement bloqué : Une distribution d'alimentation a déjà été validée aujourd'hui ({date_du_jour.strftime('%d/%m/%Y')}) pour ce Lot.", "error")
                return redirect(url_for('liste_alimentations'))

        produit_concerne = Produit.query.get(id_produit)
        if not produit_concerne:
            flash("❌ Erreur : Le produit sélectionné est introuvable au catalogue.", "error")
            return redirect(url_for('liste_alimentations'))

        # -----------------------------------------------------------------
        # CAS A : MODE MODIFICATION SÉCURISÉ (UPDATE)
        # -----------------------------------------------------------------
        if id_alimentation_modif and id_alimentation_modif.strip() != "":
            fiche_existante = Alimentation.query.get(int(id_alimentation_modif))
            if fiche_existante:
                if est_ouvrier and fiche_existante.id_user != user_id_connecte:
                    flash("❌ Action non autorisée : Vous ne pouvez pas modifier cet enregistrement.", "error")
                    return redirect(url_for('liste_alimentations'))
                
                fiche_existante.date_alimentation = date_alimentation_objet
                fiche_existante.id_produit = id_produit
                fiche_existante.quantite = quantite
                fiche_existante.id_lot = id_lot
                
                db.session.commit()
                db.session.expire_all()
                flash("✔ La fiche de consommation a été corrigée. Calculs mis à jour !", "success")
            else:
                flash("❌ Erreur : Fiche d'alimentation introuvable.", "error")
                return redirect(url_for('liste_alimentations'))

        # -----------------------------------------------------------------
        # CAS B : MODE NOUVEL AJOUT DYNAMIQUE (INSERT)
        # -----------------------------------------------------------------
        else:
            config_admin = Configuration.query.first()
            
            # 🔥 FIX ANTI-CRASH : Utilisation de getattr pour parer l'absence de colonnes en BDD
            stock_initial_admin = getattr(config_admin, 'stock_initial_cycle', 2580.0)
            if stock_initial_admin is None: 
                stock_initial_admin = 2580.0

            # Calcul du stock actuel restant pour ce mois avant de valider la sortie
            total_historique_mois = db.session.query(func.sum(Alimentation.quantite)).filter(
                extract('year', Alimentation.date_alimentation) == date_du_jour.year,
                extract('month', Alimentation.date_alimentation) == date_du_jour.month
            ).scalar() or 0.0
            
            stock_reel_dispo = float(stock_initial_admin) - float(total_historique_mois)
            
            if stock_reel_dispo < quantite:
                flash(f"❌ Stock insuffisant ! Il ne reste que {round(stock_reel_dispo, 1)} Kg pour ce mois.", "error")
                return redirect(url_for('liste_alimentations'))

            nouvelle_distribution = Alimentation(
                date_alimentation=date_alimentation_objet,
                id_produit=id_produit,
                quantite=quantite,
                id_lot=id_lot,
                id_user=user_id_connecte
            )
            
            db.session.add(nouvelle_distribution)
            db.session.commit()
            db.session.expire_all()
            
            flash(f"✔ Distribution enregistrée ! -{int(quantite)} Kg déduits du stock du mois.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'écriture dans le registre : {str(e)}", "error")
    finally:
        db.session.remove()

    return redirect(url_for('liste_alimentations'))

# =====================================================================
# DÉCLENCHEURS DE STOCK AUTOMATIQUES (HOOKS) - VERSION NETTOYÉE ET CORRIGÉE
# =====================================================================
@event.listens_for(Alimentation, 'after_insert')
def deduire_stock_apres_distribution(mapper, connection, target):
    """Soustrait proprement la quantité distribuée du stock via SQL natif après un ajout"""
    try:
        quantite_entiere = int(float(target.quantite))
        if quantite_entiere > 0:
            # Mise à jour directe en base de données pour éviter les conflits d'états d'objets
            connection.execute(
                db.text("UPDATE produit SET stock = stock - :qte WHERE id_produit = :id_prod"),
                {"qte": quantite_entiere, "id_prod": target.id_produit}
            )
    except (ValueError, TypeError, Exception):
        pass

@event.listens_for(Alimentation, 'before_update')
def réajuster_stock_avant_modification(mapper, connection, target):
    """Réajuste le stock si la fiche de distribution est modifiée au tableau via SQL natif"""
    try:
        # Récupération sécurisée de l'ancienne valeur directement depuis la connexion courante
        resultat = connection.execute(
            db.text("SELECT quantite FROM alimentation WHERE id_alimentation = :id_alim"),
            {"id_alim": target.id_alimentation}
        ).fetchone()
        
        if resultat:
            ancienne_quantite = int(float(resultat[0]))
            nouvelle_quantite = int(float(target.quantite))
            
            # Calcul de la différence à réajuster
            difference = nouvelle_quantite - ancienne_quantite
            
            if difference != 0:
                # Si la différence est positive, le stock diminue. Si elle est négative, le stock réaugmente.
                connection.execute(
                    db.text("UPDATE produit SET stock = stock - :diff WHERE id_produit = :id_prod"),
                    {"diff": difference, "id_prod": target.id_produit}
                )
    except (ValueError, TypeError, Exception):
        pass

@event.listens_for(Alimentation, 'after_delete')
def restituer_stock_apres_suppression(mapper, connection, target):
    """Restitue proprement les kg au stock via SQL natif si une ligne d'alimentation est retirée"""
    try:
        # Sécurité : Conversion de la quantité en nombre entier pour la table Produit
        quantite_entiere = int(float(target.quantite))
        
        if quantite_entiere > 0:
            # Utilisation de la connexion brute pour une mise à jour SQL ultra-rapide et sécurisée
            connection.execute(
                db.text("UPDATE produit SET stock = stock + :qte WHERE id_produit = :id_prod"),
                {"qte": quantite_entiere, "id_prod": target.id_produit}
            )
    except (ValueError, TypeError, Exception):
        # Évite de faire planter l'application en cas d'erreur de conversion inattendue
        pass

# ==============================================================================
# --- MODULE CROISSANCE (INTEGRATION DE LA CONSOMMATION PAR SUJET) ---
# ==============================================================================

@app.route('/croissance', methods=['GET'])
def liste_croissance():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    # 1. AUTHENTIFICATION ET DROITS STREICTS
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte:
        session.clear()
        return redirect(url_for('connexion_get'))
        
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    roles_ouvrier = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']
    
    est_admin = fonction_user in roles_admin
    est_ouvrier = fonction_user in roles_ouvrier

    if not est_admin and not est_ouvrier:
        flash("Accès refusé : Privilèges insuffisants pour consulter le registre de croissance.", "error")
        return redirect(url_for('index'))

    infos_entreprise = Configuration.query.first()
    lot_selectionne = request.args.get('lot', '')
    
    page = request.args.get('page', 1, type=int) 
    par_page = 20

    # 2. CLOISONNEMENT ET SÉLECTION AUTOMATIQUE DU DERNIER LOT EN COURS
    if est_admin:
        lots_disponibles = LotAvicole.query.order_by(LotAvicole.date_arrivee.desc()).all()
    else:
        lots_disponibles = LotAvicole.query.filter_by(id_user=user_id_connecte).order_by(LotAvicole.date_arrivee.desc()).all()
        
    ids_lots_autorises = [l.id_lot for l in lots_disponibles]

    # 🔄 EXIGENCE : Si aucun lot n'est sélectionné à l'ouverture, on force le dernier lot en cours
    if not lot_selectionne or lot_selectionne.strip() == "":
        if lots_disponibles:
            # On prend le premier de la liste triée par date décroissante (le plus récent)
            id_lot_cible = lots_disponibles[0].id_lot
            lot_actif_str = str(id_lot_cible)
        else:
            id_lot_cible = None
            lot_actif_str = ""
    else:
        id_lot_cible = int(lot_selectionne)
        lot_actif_str = lot_selectionne

    # 3. SÉCURITÉ ET CALCUL DES 4 INDICATEURS DU LOT EN COURS
    total_consomme = 0.0
    ic = 0.0
    effectif_actuel = 0
    conso_par_sujet_g = 0.0
    historique_pesees = []
    pagination = None

    if id_lot_cible:
        # Sécurité anti-fraude d'URL pour les ouvriers
        if id_lot_cible not in ids_lots_autorises:
            flash("❌ Accès refusé : Ce lot ne vous est pas attribué.", "error")
            return redirect(url_for('liste_croissance'))

        # A. Requête paginée de l'historique des pesées pour ce lot spécifique
        query_pesees = SuiviCroissance.query.filter_by(id_lot=id_lot_cible)
        pagination = query_pesees.order_by(SuiviCroissance.date_pesee.desc()).paginate(
            page=page, per_page=par_page, error_out=False
        )
        historique_pesees = pagination.items

        # B. Calcul 1 : Aliments cumulés du lot spécifique
        total_consomme = db.session.query(func.sum(Alimentation.quantite)).filter_by(id_lot=id_lot_cible).scalar() or 0.0

        # C. Calcul 2 : Oiseaux vivants actuels du lot spécifique
        lot_actuel_obj = LotAvicole.query.get(id_lot_cible)
        total_morts = db.session.query(func.sum(Mortalite.nombre)).filter_by(id_lot=id_lot_cible).scalar() or 0
        if lot_actuel_obj:
            effectif_actuel = lot_actuel_obj.effectif_initial - total_morts

        # D. Calcul 3 : Récupération de la dernière pesée du lot pour l'IC
        derniere_pesee = SuiviCroissance.query.filter_by(id_lot=id_lot_cible).order_by(SuiviCroissance.date_pesee.desc()).first()

        # E. Calcul de l'Indice de Consommation (IC)
        if historique_pesees and derniere_pesee and derniere_pesee.poids_moyen > 0 and effectif_actuel > 0:
            biomasse_totale_kg = (effectif_actuel * derniere_pesee.poids_moyen) / 1000.0
            if biomasse_totale_kg > 0:
                ic = round(total_consomme / biomasse_totale_kg, 2)

        # F. Calcul 4 : Consommation cumulée moyenne par sujet (en Grammes)
        if total_consomme > 0 and effectif_actuel > 0:
            conso_par_sujet_g = round((total_consomme / effectif_actuel) * 1000.0, 0)

        # Normalisation des dates
        for p in historique_pesees:
            p.date_iso = p.date_pesee.strftime('%Y-%m-%d') if p.date_pesee else ''
            p.date_affichage = p.date_pesee.strftime('%d/%m/%Y') if p.date_pesee else ''

    return render_template(
        'suivicroissance.html', 
        lots=lots_disponibles, 
        pesees=historique_pesees,
        lot_actif=lot_actif_str, # Transmet l'ID du dernier lot forcé au sélecteur HTML
        total_consomme=total_consomme,
        ic=ic,
        effectif_actuel=effectif_actuel,
        conso_sujet=conso_par_sujet_g,
        entreprise=infos_entreprise,
        pagination=pagination,
        est_admin=est_admin
    )

@app.route('/croissance/ajouter', methods=['POST'])
def ajouter_pesee():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    # 1. AUTHENTIFICATION & CLOISONNEMENT STRICT DES RÔLES
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte:
        session.clear()
        return redirect(url_for('connexion_get'))
        
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    roles_ouvrier = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']
    
    est_admin = fonction_user in roles_admin
    est_ouvrier = fonction_user in roles_ouvrier

    # ❌ BLOCAGE DE SÉCURITÉ 1 : Profil non autorisé
    if not est_admin and not est_ouvrier:
        flash("Accès refusé : Privilèges insuffisants pour administrer le registre.", "error")
        return redirect(url_for('liste_croissance'))

    # Récupération des données du formulaire
    id_pesee_modif = request.form.get('id_pesee_modif')
    id_lot = request.form.get('id_lot')
    date_pesee_str = request.form.get('date_pesee')
    poids_moyen = request.form.get('poids_moyen')
    age_semaines = request.form.get('age_semaines')

    if not all([id_lot, date_pesee_str, poids_moyen, age_semaines]):
        flash("Veuillez remplir tous les champs obligatoires (*).", "error")
        return redirect(url_for('liste_croissance'))

    try:
        id_lot_int = int(id_lot)
        
        # 🔒 SÉCURITÉ 2 : L'employé possède-t-il ce lot ? (Anti-fraude de lot)
        if not est_admin:
            lot_attribue = LotAvicole.query.filter_by(id_lot=id_lot_int, id_user=user_id_connecte).first()
            if not lot_attribue:
                flash("❌ Enregistrement refusé : Vous n'êtes pas responsable de ce lot.", "error")
                return redirect(url_for('liste_croissance'))

        # -----------------------------------------------------------------
        # ❌ SÉCURITÉ 3 : INTERDICTION STRICTE D'UNE DATE DIFFÉRENTE D'AUJOURD'HUI
        # -----------------------------------------------------------------
        date_du_jour = datetime.now().date()
        try:
            date_pesee_objet = datetime.strptime(date_pesee_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            date_pesee_objet = date_du_jour

        if date_pesee_objet != date_du_jour:
            flash(f"❌ Saisie refusée : Impossible d'enregistrer un contrôle pour une date différente d'aujourd'hui ({date_du_jour.strftime('%d/%m/%Y')}).", "error")
            return redirect(url_for('liste_croissance') + f"?lot={id_lot_int}")

        # -----------------------------------------------------------------
        # ❌ SÉCURITÉ 4 : INTERDICTION DE DEUX PESÉES LE MÊME JOUR POUR UN LOT
        # -----------------------------------------------------------------
        fiche_doublon = SuiviCroissance.query.filter_by(id_lot=id_lot_int, date_pesee=date_du_jour).first()
        if fiche_doublon:
            # S'il s'agit d'un nouvel ajout OU si une modification essaie d'écraser une autre pesée existante
            if not id_pesee_modif or int(id_pesee_modif) != fiche_doublon.id_pesee:
                flash(f"❌ Enregistrement bloqué : Un contrôle pondéral a déjà été validé aujourd'hui ({date_du_jour.strftime('%d/%m/%Y')}) pour ce Lot.", "error")
                return redirect(url_for('liste_croissance') + f"?lot={id_lot_int}")

        # -----------------------------------------------------------------
        # CAS A : MODIFICATION EXISTANTE (ÉDITION)
        # -----------------------------------------------------------------
        if id_pesee_modif and id_pesee_modif.strip() != "":
            fiche = SuiviCroissance.query.get(int(id_pesee_modif))
            if fiche:
                # Anti-fraude d'ID : Un employé classique ne peut pas modifier la pesée d'un lot tiers
                if not est_admin and fiche.lot_avicole.id_user != user_id_connecte:
                    flash("❌ Action interdite.", "error")
                    return redirect(url_for('liste_croissance'))
                
                fiche.id_lot = id_lot_int
                fiche.date_pesee = date_pesee_objet
                fiche.poids_moyen = float(poids_moyen)
                fiche.age_semaines = int(age_semaines)
                db.session.commit()
                
                # Vider la mémoire cache de la session pour recalculer l'IC et la biomasse
                db.session.expire_all()
                flash("La fiche de pesée et de croissance a été mise à jour.", "success")
                
        # -----------------------------------------------------------------
        # CAS B : INSERTION D'UN NOUVEAU CONTRÔLE PONDÉRAL (INSERT)
        # -----------------------------------------------------------------
        else:
            nouvelle_pesee = SuiviCroissance(
                id_lot=id_lot_int,
                date_pesee=date_pesee_objet,
                poids_moyen=float(poids_moyen),
                age_semaines=int(age_semaines),
                id_user=user_id_connecte # Scelle la traçabilité de l'auteur
            )
            db.session.add(nouvelle_pesee)
            db.session.commit()
            
            db.session.expire_all()
            flash("Pesée enregistrée avec succès au registre de croissance.", "success")
            
        return redirect(url_for('liste_croissance') + f"?lot={id_lot_int}")

    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'écriture dans le registre : {str(e)}", "error")
        return redirect(url_for('liste_croissance'))

# =======================================================
# ROUTINES APPLICATIVES : GESTION DE PRODUCTION D'OEUFS
# =======================================================

@app.route('/productions', methods=['GET'])
def liste_productions():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    
    # 1. Identification de l'opérateur connecté et de ses droits étendus
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte:
        return redirect(url_for('connexion_get'))
        
    # Normalisation stricte de la chaîne de caractères
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    
    # Définition des matrices de rôles PROMAS Aviculture
    roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    roles_ouvrier = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']
    
    est_admin = fonction_user in roles_admin
    est_ouvrier = fonction_user in roles_ouvrier
    
    # Sécurité globale : si le rôle n'existe pas dans le système
    if not est_admin and not est_ouvrier:
        flash("❌ Accès refusé : Votre profil n'est pas autorisé à consulter cette page.", "error")
        return redirect(url_for('index')) # Redirection vers le tableau de bord général

    # 2. Gestion de la configuration d'entreprise (Sécurité si la table est vide)
    infos_entreprise = Configuration.query.first()
    if not infos_entreprise:
        try:
            infos_entreprise = Configuration(
                raison_sociale="PROMAS Aviculture",
                adresse="Dakar, Sénégal",
                telephone="+221 77 345 69 34",
                email="contact@promas.sn"
            )
            db.session.add(infos_entreprise)
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 3. Capture des filtres issus des arguments GET de l'URL et pagination
    lot_selectionne = request.args.get('lot', '')
    mois_selectionne = request.args.get('mois', '')
    annee_selectionnee = request.args.get('annee', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20 # Nombre de lignes par page pour un affichage ultra-rapide

    # 4. Cloisonnement multi-utilisateur strict en fonction du rôle
    if est_admin:
        # Les administrateurs, gérants, directeurs et comptables voient tout
        lots_disponibles = LotAvicole.query.all()
        query_base = ProductionOeufs.query
    else:
        # L'ouvrier/agent/technicien ne peut requêter que ses lots attribués
        lots_disponibles = LotAvicole.query.filter_by(id_user=user_id_connecte).all()
        query_base = ProductionOeufs.query.filter(ProductionOeufs.id_user == user_id_connecte)

    # Application progressive des filtres multicritères sur la base cloisonnée
    if lot_selectionne and lot_selectionne.strip() != "":
        query_base = query_base.filter(ProductionOeufs.id_lot == int(lot_selectionne))
    if mois_selectionne and mois_selectionne.strip() != "":
        query_base = query_base.filter(db.extract('month', ProductionOeufs.date_production) == int(mois_selectionne))
    if annee_selectionnee and annee_selectionnee.strip() != "":
        query_base = query_base.filter(db.extract('year', ProductionOeufs.date_production) == int(annee_selectionnee))

    # Tri par date décroissante natif au niveau de la BDD pour la pagination
    query_base = query_base.order_by(ProductionOeufs.date_production.desc())
    
    # Exécution de la pagination native (SQL OFFSET / LIMIT)
    pagination = query_base.paginate(page=page, per_page=per_page, error_out=False)
    fiches_productions = pagination.items

    # 5. Normalisation des formats et calcul progressif de l'effectif et du taux de ponte
    for p in fiches_productions:
        p.date_iso = p.date_production.strftime('%Y-%m-%d') if p.date_production else ''
        p.date_affichage = p.date_production.strftime('%d/%m/%Y') if p.date_production else ''
        
        if p.date_production:
            # A. Somme des pertes des jours STRICTEMENT PRÉCÉDENTS
            morts_jours_avant = db.session.query(db.func.sum(Mortalite.nombre)).filter(
                Mortalite.id_lot == p.id_lot,
                Mortalite.date_mortalite < p.date_production
            ).scalar() or 0
            
            # B. Récupération du premier ID de mortalité du jour pour caler le cumul progressif
            morts_num = db.session.query(Mortalite.id_mortalite).filter(
                Mortalite.id_lot == p.id_lot,
                Mortalite.date_mortalite == p.date_production
            ).limit(1).scalar() or 0
            
            # C. Somme des pertes déclarées jusqu'à ce moment précis du jour J
            morts_jour_meme = db.session.query(db.func.sum(Mortalite.nombre)).filter(
                Mortalite.id_lot == p.id_lot,
                Mortalite.date_mortalite == p.date_production,
                Mortalite.id_mortalite <= morts_num
            ).scalar() or 0
            
            total_pertes_cumulees = morts_jours_avant + morts_jour_meme
            poules_vivantes = (p.lot_avicole.effectif_initial if p.lot_avicole else 0) - total_pertes_cumulees
            p.poules_vivantes = poules_vivantes if poules_vivantes > 0 else 0
            
            # D. Calcul exact du Taux de Ponte basé sur l'effectif résiduel de cette ligne
            if p.poules_vivantes > 0:
                p.taux_ponte = round((p.nombre_oeufs / p.poules_vivantes) * 100, 1)
            else:
                p.taux_ponte = 0.0

    return render_template(
        'suiviproduction.html', 
        productions=fiches_productions,
        pagination=pagination,
        lots=lots_disponibles,
        lot_actif=str(lot_selectionne),
        mois_actif=str(mois_selectionne),
        annee_actif=str(annee_selectionnee),
        entreprise=infos_entreprise,
        est_admin=est_admin # Variable qui pilote le masquage automatique du bouton Imprimer en HTML
    )


@app.route('/productions/ajouter', methods=['POST'])
def ajouter_production():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    est_admin = utilisateur_connecte.Fonction.lower() in ['administrateur', 'admin', 'gérant']
    
    try:
        id_production_modif = request.form.get('id_production_modif')
        id_lot = request.form.get('id_lot')
        date_production_str = request.form.get('date_production')
        nombre_oeufs = int(request.form.get('nombre_oeufs') or 0)
        oeufs_casses = int(request.form.get('oeufs_casses') or 0)
        
        if not all([id_lot, date_production_str]):
            flash("Veuillez remplir tous les champs obligatoires (*).", "error")
            return redirect(url_for('liste_productions'))
            
        id_lot_int = int(id_lot)
        
        if not est_admin:
            lot_attribue = LotAvicole.query.filter_by(id_lot=id_lot_int, id_user=user_id_connecte).first()
            if not lot_attribue:
                flash("❌ Enregistrement refusé : Vous n'êtes pas responsable de ce lot.", "error")
                return redirect(url_for('liste_productions'))
                
        date_production = datetime.strptime(date_production_str, '%Y-%m-%d').date()
        lot = LotAvicole.query.get(id_lot_int)
        
        # VERROUILLAGE ULTRA-STRICT : Interdiction de saisir une date double pour le même lot
        critere_doublon = [
            ProductionOeufs.id_lot == id_lot_int, 
            ProductionOeufs.date_production == date_production
        ]
        if id_production_modif and id_production_modif.strip() != "":
            # En cas de mise à jour, on exclut la ligne courante de la recherche de doublons
            critere_doublon.append(ProductionOeufs.id_production != int(id_production_modif))
            
        existe_deja = ProductionOeufs.query.filter(and_(*critere_doublon)).first()
        if existe_deja:
            flash(f"❌ Enregistrement refusé : Un rapport de ramassage existe déjà pour le lot {lot.code_lot} à la date du {date_production.strftime('%d/%m/%Y')}.", "error")
            return redirect(url_for('liste_productions'))
        
        if id_production_modif and id_production_modif.strip() != "":
            fiche = ProductionOeufs.query.get(int(id_production_modif))
            if fiche:
                if not est_admin and fiche.id_user != user_id_connecte:
                    flash("❌ Action interdite : Vous ne pouvez pas modifier ce rapport.", "error")
                    return redirect(url_for('liste_productions'))
                fiche.id_lot = id_lot_int
                fiche.date_production = date_production
                fiche.nombre_oeufs = nombre_oeufs
                fiche.oeufs_casses = oeufs_casses
                flash(f"Le rapport de ponte du lot {lot.code_lot} a été rectifié !", "success")
        else:
            nouvelle_ponte = ProductionOeufs(
                id_lot=id_lot_int,
                date_production=date_production,
                nombre_oeufs=nombre_oeufs,
                oeufs_casses=oeufs_casses,
                id_user=user_id_connecte
            )
            db.session.add(nouvelle_ponte)
            flash(f"Le ramassage du jour pour le lot {lot.code_lot} a été enregistré !", "success")
            
        db.session.commit()
        parties = date_production_str.split('-')
        return redirect(url_for('liste_productions') + f"?lot={id_lot}&mois={parties[1]}&annee={parties[0]}")
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'écriture dans le registre de ponte : {str(e)}", "error")
        return redirect(url_for('liste_productions'))

# =======================================================================
# ROUTINES APPLICATIVES : GESTION DES PRODUITS (MATIÈRES) - ULTRA RAPIDE
# =======================================================================

@app.route('/produits', methods=['GET'])
def liste_produits():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # 1. SÉCURITÉ : Audit et filtrage des rôles (Admin et Caissiers autorisés)
        utilisateur_connecte = Users.query.get(session['user_id'])
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        roles_autorises = roles_superieurs + ['caissier', 'caissière']
        
        if fonction_user not in roles_autorises:
            flash("Accès refusé : Privilèges insuffisants pour consulter le catalogue.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs

        # Variables de filtrage temporel et catégoriel
        maintenant = datetime.now()
        mois_selectionne = request.args.get('filter_mois', maintenant.strftime('%m'))
        annee_selectionnee = request.args.get('filter_annee', maintenant.strftime('%Y'))
        cat_selectionnee = request.args.get('filter_categorie', '')
        
        # Paramètres de pagination
        page = request.args.get('page', 1, type=int)
        par_page = 40

        # 2. CONSTRUCTION DE LA REQUÊTE FILTRÉE ET CLOISONNÉE
        query_produits = Produit.query.options(joinedload(Produit.user)).filter(
            extract('month', Produit.date_enregistrement) == int(mois_selectionne),
            extract('year', Produit.date_enregistrement) == int(annee_selectionnee)
        )
        
        if cat_selectionnee:
            query_produits = query_produits.filter(Produit.categorie == cat_selectionnee)
            
        # CLOISONNEMENT VISUEL STRICT : Le caissier ne voit QUE ses propres produits
        if not est_admin_ou_comptable:
            query_produits = query_produits.filter(Produit.id_user == session['user_id'])
            
        # Application de la pagination native
        pagination = query_produits.order_by(Produit.designation.asc()).paginate(
            page=page, per_page=par_page, error_out=False
        )
        
        tous_les_produits = pagination.items
        infos_entreprise = Configuration.query.first()
        
        # 3. OPTIMISATION DE MASSE : Extraction groupée des derniers prix d'achat
        id_produits = [p.id_produit for p in tous_les_produits]
        derniers_prix_map = {}
        
        if id_produits:
            lignes_achats = db.session.query(
                achat_produit.c.id_produit,
                achat_produit.c.prix_unitaire
            ).filter(achat_produit.c.id_produit.in_(id_produits))\
             .order_by(achat_produit.c.id_achat.asc()).all()
             
            for id_prod, pu in lignes_achats:
                derniers_prix_map[id_prod] = pu
                
        # 4. CALCUL FINANCIER EN MÉMOIRE RAM (Vitesse éclair - Syntaxe validée Python 3)
        valeur_totale_stock = 0.0
        for prod in tous_les_produits:
            dernier_prix = derniers_prix_map.get(prod.id_produit)
            
            # Correction syntaxique de la SyntaxError liée au double Walrus enchaîné
            if dernier_prix is not None:
                prod.prix_achat_moyen = float(dernier_prix)
            else:
                prod.prix_achat_moyen = float(prod.prix_achat or 0.0)
                
            quantite_physique = float(prod.stock or 0)
            if prod.categorie in ["Alimentation", "Conditionnement", "Produits vétérinaires"]:
                valeur_totale_stock += (quantite_physique * prod.prix_achat_moyen)
            else:
                valeur_totale_stock += (quantite_physique * float(prod.prix_vente or 0.0))
                
        # 5. EXTRACTION SÉCURISÉE DES ANNÉES (Conversion Row -> Int)
        annees_dispo = db.session.query(extract('year', Produit.date_enregistrement).distinct()).all()
        liste_annees = []
        for a in annees_dispo:
            if a[0] is not None:
                liste_annees.append(int(a[0]))
                
        if int(annee_selectionnee) not in liste_annees:
            liste_annees.append(int(annee_selectionnee))
            
        return render_template(
            'suiviproduits.html',
            produits=tous_les_produits,
            total_articles=pagination.total,
            valeur_stock=round(valeur_totale_stock, 0),
            entreprise=infos_entreprise,
            liste_annees=sorted(liste_annees, reverse=True),
            mois_sel=mois_selectionne,
            annee_sel=annee_selectionnee,
            cat_sel=cat_selectionnee,
            pagination=pagination,
            est_admin=est_admin_ou_comptable
        )
        
    except Exception as e:
        db.session.rollback()
        return f"<h3>⚙ Erreur Système :</h3> <p>{str(e)}</p>"

    
# =======================================================================
# ROUTINE ENREGISTREMENT ET MODIFICATION AUTOMATIQUE AVEC ID OPÉRATEUR
# =======================================================================

@app.route('/ajouter_produit', methods=['POST'])
def ajouter_produit():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # 1. SÉCURITÉ : Récupération stricte de l'utilisateur en session
        id_operateur = session['user_id']
        utilisateur_connecte = Users.query.get(id_operateur)
        
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        roles_autorises = roles_superieurs + ['caissier', 'caissière']
        
        if fonction_user not in roles_autorises:
            flash("Action interdite : Droits insuffisants.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs

        # 2. RÉCUPÉRATION DES DONNÉES DU FORMULAIRE HTML
        id_produit_modif = request.form.get('id_produit_modif')
        designation = request.form.get('designation', '').strip()
        categorie = request.form.get('categorie', '').strip()
        unite = request.form.get('unite', '').strip()
        
        prix_vente_str = request.form.get('prix_vente', '0')
        prix_achat_str = request.form.get('prix_achat', '0')
        stock_initial_str = request.form.get('stock_initial', '0')
        date_str = request.form.get('date_enregistrement')

        if not all([designation, categorie, unite, date_str]):
            flash("Veuillez remplir tous les champs obligatoires (*).", "error")
            return redirect(url_for('liste_produits'))

        prix_vente = float(prix_vente_str) if prix_vente_str else 0.0
        prix_achat = float(prix_achat_str) if prix_achat_str else 0.0
        stock_initial = float(stock_initial_str) if stock_initial_str else 0.0
        date_enregistrement = datetime.strptime(date_str, '%Y-%m-%d').date()

        # -----------------------------------------------------------------
        # CAS 1 : MODIFICATION D'UN PRODUIT EXISTANT
        # -----------------------------------------------------------------
        if id_produit_modif:
            produit = Produit.query.get(int(id_produit_modif))
            if not produit:
                flash("Produit introuvable pour la modification.", "error")
                return redirect(url_for('liste_produits'))
                
            # ANTIFRAUDE : Un caissier ne peut pas modifier la fiche d'un autre collègue
            if not est_admin_ou_comptable and produit.id_user != id_operateur:
                flash("Action interdite : Vous ne pouvez modifier que vos propres fiches.", "error")
                return redirect(url_for('liste_produits'))

            produit.designation = designation
            produit.categorie = categorie
            produit.unite = unite
            produit.prix_vente = prix_vente
            produit.prix_achat = prix_achat
            produit.stock = stock_initial
            produit.date_enregistrement = date_enregistrement
            
            db.session.commit()
            flash(f"✔ Le produit '{designation}' a été mis à jour avec succès !", "success")

        # -----------------------------------------------------------------
        # CAS 2 : INSERTION AUTOMATIQUE D'UN NOUVEAU PRODUIT (VOTRE ERREUR)
        # -----------------------------------------------------------------
        else:
            nouveau_produit = Produit(
                designation=designation,
                categorie=categorie,
                unite=unite,
                prix_vente=prix_vente,
                prix_achat=prix_achat,
                stock=stock_initial,
                date_enregistrement=date_enregistrement,
                id_user=id_operateur  # ATTACHEMENT AUTOMATIQUE ET INVISIBLE DE L'OPÉRATEUR
            )
            db.session.add(nouveau_produit)
            db.session.commit()
            flash(f"✔ Le produit '{designation}' a été ajouté au catalogue !", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Erreur système lors de l'enregistrement : {str(e)}", "error")

    return redirect(url_for('liste_produits'))


# =======================================================================
# ROUTINES APPLICATIVES : SUIVI DES ACHATS (OPTIMISÉ & PAGINÉ)
# =======================================================================

@app.route('/achats', methods=['GET'])
def liste_achats():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        utilisateur_connecte = Users.query.get(session['user_id'])
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_autorises = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable', 'caissier', 'caissière']
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        
        if fonction_user not in roles_autorises:
            flash("Accès refusé.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs
        maintenant = datetime.now()
        mois_selectionne = request.args.get('filter_mois', maintenant.strftime('%m'))
        annee_selectionnee = request.args.get('filter_annee', maintenant.strftime('%Y'))
        
        # PARAMÈTRES DE PAGINATION NATIVE DYNAMIQUE
        page = request.args.get('page', 1, type=int)
        par_page = 40  # Limite stricte de fiches chargées par écran

        # 1. Extraction des achats filtrés de la période avec jointures pré-chargées (joinedload)
        query_achats = Achat.query.options(
            joinedload(Achat.fournisseur),
            joinedload(Achat.operateur)
        ).filter(
            extract('month', Achat.date_achat) == int(mois_selectionne),
            extract('year', Achat.date_achat) == int(annee_selectionnee)
        )
        
        # Cloisonnement d'affichage : les caissiers ne voient que leurs propres opérations
        if not est_admin_ou_comptable:
            query_achats = query_achats.filter_by(id_user=session['user_id'])
            
        # Application de la pagination SQL
        pagination = query_achats.order_by(Achat.date_achat.desc(), Achat.id_achat.desc()).paginate(
            page=page, per_page=par_page, error_out=False
        )
        
        achats_enregistres = pagination.items
        id_achats_periode = [a.id_achat for a in achats_enregistres]
        
        # 2. Collecte groupée des lignes de produits en une seule passe indexée
        lignes_par_achat = {}
        if id_achats_periode:
            toutes_les_liaisons = db.session.query(achat_produit).filter(
                achat_produit.c.id_achat.in_(id_achats_periode)
            ).all()
            for li in toutes_les_liaisons:
                lignes_par_achat.setdefault(li.id_achat, []).append(li)
                
        # 3. Chargement instantané du catalogue en mémoire RAM
        tous_les_produits = {p.id_produit: p.designation for p in Produit.query.all()}
        fournisseurs = Fournisseur.query.order_by(Fournisseur.nom.asc()).all()
        produits_dropdown = Produit.query.order_by(Produit.designation.asc()).all()
        entreprise = Configuration.query.first()
        
        # 4. Reconstruction à vitesse éclair du dictionnaire pour Jinja2
        achats_formates = []
        for achat in achats_enregistres:
            liaisons = lignes_par_achat.get(achat.id_achat, [])
            for liaison in liaisons:
                nom_produit = tous_les_produits.get(liaison.id_produit, "Inconnu")
                achats_formates.append({
                    'id_achat': achat.id_achat,
                    'date_achat': achat.date_achat,
                    'nom_fournisseur': achat.fournisseur.nom if achat.fournisseur else 'Inconnu',
                    'nom_operateur': achat.operateur.NomUtilisateur if achat.operateur else 'Système',
                    'produ': nom_produit,
                    'quantite': liaison.quantite,
                    'prix_unitaire': liaison.prix_unitaire,
                    'usage_produit': liaison.usage_produit,
                    'montant_total': liaison.quantite * liaison.prix_unitaire
                })
                
        # 5. Extraction sécurisée des années distinctes (Conversion Row -> Int pur)
        annees_dispo = db.session.query(extract('year', Achat.date_achat).distinct()).all()
        liste_annees = []
        for a in annees_dispo:
            if a[0] is not None:
                liste_annees.append(int(a[0]))
                
        if int(annee_selectionnee) not in liste_annees:
            liste_annees.append(int(annee_selectionnee))
            
        return render_template(
            'suiviachats.html',
            achats=achats_formates,
            fournisseurs=fournisseurs,
            produits=produits_dropdown,
            entreprise=entreprise,
            annees=sorted(liste_annees, reverse=True),
            mois_sel=mois_selectionne,
            annee_sel=annee_selectionnee,
            pagination=pagination  # Transmis au template pour dessiner les boutons
        )
        
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'affichage : {str(e)}", "error")
        return redirect(url_for('index'))

@app.route('/achats/ajouter', methods=['POST'])
def ajouter_achat():
    # 1. Vérification de la session utilisateur
    if 'user_id' not in session:
        return jsonify({
            'success': False, 
            'message': 'Vous devez être connecté pour effectuer cette action.'
        }), 401

    try:
        # 2. Récupération des données JSON envoyées par JavaScript
        donnees = request.get_json()
        if not donnees:
            return jsonify({'success': False, 'message': 'Aucune donnée reçue.'}), 400

        id_fournisseur = donnees.get('id_fournisseur')
        date_saisie = donnees.get('date_achat')
        panier = donnees.get('panier', [])

        if not id_fournisseur or not panier:
            return jsonify({'success': False, 'message': 'Fournisseur ou panier manquant.'}), 400

        # Convertir la date du format HTML (YYYY-MM-DD) au format SQL Date
        if date_saisie:
            date_achat = datetime.strptime(date_saisie, '%Y-%m-%d').date()
        else:
            date_achat = datetime.now().date()

        # 3. Création du Bon d'Achat principal (Un achat regroupe plusieurs lignes)
        nouvel_achat = Achat(
            id_fournisseur=id_fournisseur,
            date_achat=date_achat,
            id_user=session['user_id']  # Liaison avec l'employé connecté
        )
        db.session.add(nouvel_achat)
        db.session.flush()  # Récupère instantanément l'id_achat sans valider la transaction globale

        # 4. Boucle de traitement sur chaque produit du panier
        for item in panier:
            id_produit = item.get('id_produit')
            quantite = float(item.get('quantite', 0))
            prix_unitaire = float(item.get('prix_unitaire', 0))
            usage = item.get('usage_produit', 'vente')

            # Validation du produit en base
            produit_cible = Produit.query.get(id_produit)
            if not produit_cible:
                db.session.rollback()
                return jsonify({'success': False, 'message': f'Produit ID {id_produit} introuvable.'}), 404

            # --- REGLE DE GESTION : Pas d'achat de sa propre production ---
            if produit_cible.categorie == "Production (Stock-Vente)":
                db.session.rollback()
                return jsonify({
                    'success': False, 
                    'message': f"Refusé : Le produit '{produit_cible.designation}' provient de votre propre production."
                }), 400

            # --- REGLE DE GESTION : Forcer l'usage interne ---
            if produit_cible.categorie in ["Conditionnement", "Alimentation"] and usage != "nourrir":
                usage = "nourrir"

            # Insertion de la ligne dans la table d'association achat_produit
            statement = achat_produit.insert().values(
                id_achat=nouvel_achat.id_achat,
                id_produit=id_produit,
                quantite=quantite,
                prix_unitaire=prix_unitaire,
                usage_produit=usage
            )
            db.session.execute(statement)

            # Ajustement automatique du stock du produit dans le catalogue
            produit_cible.stock += int(quantite)

        # 5. Validation de la transaction complète
        db.session.commit()
        
        # Flash message pour le prochain rechargement de page initié par le JS
        flash("L'approvisionnement multi-produits a été enregistré avec succès !", "success")
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f"Erreur lors de l'enregistrement : {str(e)}"}), 500

    
@app.route('/achats/supprimer/<int:id_achat>', methods=['POST'])
def supprimer_achat(id_achat):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        achat_principal = Achat.query.get(id_achat)
        if not achat_principal:
            flash("Achat introuvable.", "error")
            return redirect(url_for('liste_achats'))
            
        utilisateur_connecte = Users.query.get(session['user_id'])
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        
        # Étendre la liste des rôles d'autorité autorisés à annuler les saisies des autres
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        est_admin_ou_comptable = fonction_user in roles_superieurs
        
        # SÉCURITÉ : Si ce n'est pas son achat ET qu'il n'a pas un rôle supérieur -> Refusé
        if achat_principal.id_user != session['user_id'] and not est_admin_ou_comptable:
            flash("Action interdite : Vous ne pouvez pas annuler l'achat d'un autre utilisateur.", "error")
            return redirect(url_for('liste_achats'))
            
        # 🎯 CORRECTION PANIER : Récupérer TOUTES les lignes de produits associées à cet achat (.all())
        liaisons = db.session.query(achat_produit).filter_by(id_achat=id_achat).all()
        
        # Parcourir chaque produit pour reculer les stocks physiques du catalogue
        for liaison in liaisons:
            produit_cible = Produit.query.get(liaison.id_produit)
            if produit_cible:
                # On soustrait la quantité initialement achetée pour rétablir le stock d'origine
                produit_cible.stock -= int(liaison.quantite)
                
        # Suppression sécurisée des lignes dans la table d'association achat_produit
        db.session.execute(achat_produit.delete().where(achat_produit.c.id_achat == id_achat))
        
        # Suppression du Bon d'Achat parent
        db.session.delete(achat_principal)
        
        # Validation définitive de l'annulation en bloc
        db.session.commit()
        flash("L'achat complet (multi-produits) a été annulé et les stocks ont été réajustés avec succès.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de l'annulation : {str(e)}", "error")
        
    return redirect(url_for('liste_achats'))

# -------------------------------------------------------
# VENTE AUX CLIENTS
# -------------------------------------------------------
@app.route('/ventes', methods=['GET'])
def suivi_ventes():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    try:
        utilisateur_connecte = Users.query.get(session['user_id'])
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_autorises = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable', 'caissier', 'caissière']
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        
        if fonction_user not in roles_autorises:
            flash("Accès refusé : Droits insuffisants.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs
        maintenant = datetime.now()
        mois_selectionne = request.args.get('filter_mois', maintenant.strftime('%m'))
        annee_selectionnee = request.args.get('filter_annee', maintenant.strftime('%Y'))
        user_selectionne = request.args.get('filter_user', '')

        # 1. PARAMÈTRE DE PAGINATION DYNAMIQUE ACCUEILLI DEPUIS L'URL
        page = request.args.get('page', 1, type=int)
        par_page = 50  # Nombre de ventes affichées par page

        # Construction de la requête de base avec jointures pour la rapidité
        query_ventes = Vente.query.options(joinedload(Vente.client), joinedload(Vente.operateur)).filter(
            extract('month', Vente.date_vente) == int(mois_selectionne),
            extract('year', Vente.date_vente) == int(annee_selectionnee)
        )
        
        if not est_admin_ou_comptable:
            query_ventes = query_ventes.filter_by(id_user=session['user_id'])
        elif user_selectionne:
            query_ventes = query_ventes.join(Users).filter(Users.NomUtilisateur == user_selectionne)
            
        # 2. APPLICATION DE LA PAGINATION SUR LA REQUÊTE SQL
        pagination = query_ventes.order_by(Vente.date_vente.desc()).paginate(
            page=page, per_page=par_page, error_out=False
        )
        
        # On extrait les ventes de la page en cours (.items)
        ventes_brutes = pagination.items
        id_ventes_periode = [v.id_vente for v in ventes_brutes]
        
        lignes_par_vente = {}
        if id_ventes_periode:
            toutes_les_lignes = db.session.query(vente_produit).filter(
                vente_produit.c.id_vente.in_(id_ventes_periode)
            ).all()
            for li in toutes_les_lignes:
                lignes_par_vente.setdefault(li.id_vente, []).append(li)
                
        catalogue_produits = {p.id_produit: p for p in Produit.query.all()}
        ventes_formatees = []
        total_ca = 0.0
        total_marge_globale = 0.0
        
        for v in ventes_brutes:
            liste_produits_vente = []
            montant_total_vente = 0.0
            marge_totale_vente = 0.0
            
            for liaison in lignes_par_vente.get(v.id_vente, []):
                prod = catalogue_produits.get(liaison.id_produit)
                designation_produit = prod.designation if prod else "Produit inconnu"
                prix_achat_hist = prod.prix_achat if prod else 0.0
                
                total_article = liaison.quantite * liaison.prix_unitaire
                marge_article = (liaison.prix_unitaire - prix_achat_hist) * liaison.quantite
                
                montant_total_vente += total_article
                marge_totale_vente += marge_article
                
                liste_produits_vente.append({
                    'designation': designation_produit,
                    'quantite': liaison.quantite,
                    'prix_unitaire': liaison.prix_unitaire,
                    'total_ligne': total_article
                })
                
            total_ca += montant_total_vente
            total_marge_globale += marge_totale_vente
            
            ventes_formatees.append({
                'id_vente': v.id_vente,
                'date_vente': v.date_vente,
                'nom_client': v.client.nom if v.client else "Client inconnu",
                'operateur': v.operateur.NomUtilisateur if v.operateur else "Système",
                'produits': liste_produits_vente,
                'montant_total': montant_total_vente,
                'marge_realisee': marge_totale_vente
            })
            
        clients = Client.query.order_by(Client.nom.asc()).all()
        entreprise_config = Configuration.query.first()
        liste_users = [u[0] for u in db.session.query(Users.NomUtilisateur).distinct().all() if u[0] is not None]
        liste_annees = [int(a[0]) for a in db.session.query(extract('year', Vente.date_vente).distinct()).all() if a[0] is not None]
        
        if int(annee_selectionnee) not in liste_annees:
            liste_annees.append(int(annee_selectionnee))
            
        # 3. L'INJECTION DE 'pagination=pagination' TOUT EN BAS REVIENT ICI :
        return render_template(
            'suiviventes.html', ventes=ventes_formatees, total_ca=round(total_ca, 2),
            total_benefice_ventes=round(total_marge_globale, 2), clients=clients,
            produits=catalogue_produits.values(), liste_users=liste_users,
            liste_annees=sorted(liste_annees, reverse=True), mois_sel=mois_selectionne,
            annee_sel=annee_selectionnee, user_sel=user_selectionne, entreprise=entreprise_config,
            pagination=pagination
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'affichage du journal des ventes : {str(e)}", "error")
        return redirect(url_for('index'))


@app.route('/ventes/ajouter', methods=['POST'])
def ajouter_vente():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # Récupération des informations d'en-tête du bon de vente
        id_client_str = request.form.get('id_client')
        if not id_client_str:
            flash("❌ Erreur : Veuillez sélectionner un client valide.", "error")
            return redirect(url_for('suivi_ventes'))
            
        id_client = int(id_client_str)
        date_str = request.form.get('date_vente')
        date_vente = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()

        # Récupération des listes de tableaux du panier d'articles
        id_produits_list = request.form.getlist('id_produit[]')
        quantites_list = request.form.getlist('quantite[]')
        prix_unitaires_list = request.form.getlist('prix_unitaire[]')

        # Fallback de secours pour la saisie unitaire (si notation sans crochets [])
        if not id_produits_list and request.form.get('id_produit'):
            id_produits_list = [request.form.get('id_produit')]
            quantites_list = [request.form.get('quantite', 0.0)]
            prix_unitaires_list = [request.form.get('prix_unitaire', 0.0)]

        if not id_produits_list:
            flash("❌ Erreur : Aucun produit n'a été sélectionné dans le panier.", "error")
            return redirect(url_for('suivi_ventes'))

        # -----------------------------------------------------------------
        # ÉTAPE 1 : VALIDATION GLOBALE RÉGLEMENTAIRE DES STOCKS & CATÉGORIES
        # -----------------------------------------------------------------
        # 🎯 RÈGLE DE GESTION : Alignement strict sur vos 5 catégories d'articles
        categories_interdites = [
            "Alimentation",                                     # Catégorie 2 (Consommation interne uniquement)
            "Alimentation (Stocks pour la consommation uniquement)", 
            "Conditionnement", 
            "Produits vétérinaires",                             # Catégorie 5 (Soins internes de la ferme)
            "Produits vétérinaires & Consommables (Stocks)"
        ]

        for i in range(len(id_produits_list)):
            id_p = int(id_produits_list[i])
            qte = float(quantites_list[i])
            
            prod = db.session.get(Produit, id_p)
            if not prod:
                flash("❌ Erreur : Un des produits sélectionnés est introuvable au catalogue.", "error")
                return redirect(url_for('suivi_ventes'))

            # 🎯 VERROUILLAGE DES RÈGLES DE GESTION DES CATÉGORIES INTERNES
            if prod.categorie in categories_interdites:
                flash(f"❌ Vente refusée ! Le produit '{prod.designation}' appartient à la catégorie '{prod.categorie}' réservée à l'usage interne de l'exploitation (Soins ou Nutrition).", "error")
                return redirect(url_for('suivi_ventes'))

            # 🎯 VÉRIFICATION SÉCURISÉE DES STOCKS PHYSIQUES DISPONIBLES
            if float(prod.stock or 0.0) < qte:
                flash(f"❌ Vente refusée ! Stock insuffisant pour l'article '{prod.designation}'. (Disponible en magasin: {prod.stock})", "error")
                return redirect(url_for('suivi_ventes'))

        # -----------------------------------------------------------------
        # ÉTAPE 2 : CRÉATION DU BON DE VENTE UNIQUEMENT SI TOUT EST VALIDE
        # -----------------------------------------------------------------
        # Traçabilité complète liée au NumUser de l'opérateur ou caissier connecté
        nouvelle_vente = Vente(
            id_client=id_client, 
            date_vente=date_vente, 
            id_user=session['user_id']
        )
        db.session.add(nouvelle_vente)
        db.session.flush() # Génère instantanément l'id_vente pour la table d'association

        # -----------------------------------------------------------------
        # ÉTAPE 3 : INSERTION DES ARTICLES ET DÉDUCTION SÉCURISÉE DES STOCKS
        # -----------------------------------------------------------------
        for i in range(len(id_produits_list)):
            id_p = int(id_produits_list[i])
            qte = float(quantites_list[i])
            pu = float(prix_unitaires_list[i])
            
            prod = db.session.get(Produit, id_p)
            
            # Figer les prix réels facturés au client dans la table de liaison n,n
            statement = vente_produit.insert().values(
                id_vente=nouvelle_vente.id_vente,
                id_produit=id_p,
                quantite=qte,
                prix_unitaire=pu
            )
            db.session.execute(statement)

            # Déduction décimale du stock pour préserver la précision (ex: revente partielle)
            prod.stock -= qte

        # -----------------------------------------------------------------
        # ÉTAPE 4 : CRÉATION AUTOMATIQUE DE LA FACTURE COMPTABLE ASSOCIÉE
        # -----------------------------------------------------------------
        date_bloc = date_vente.strftime('%Y%m%d')
        numero_unique_facture = f"FAC-{date_bloc}-{nouvelle_vente.id_vente}"
        
        nouvelle_facture = Facture(
            numero_facture=numero_unique_facture,
            date_facture=date_vente,
            id_vente=nouvelle_vente.id_vente,
            id_client=id_client,
            id_user=session['user_id'], # Empreinte numérique de l'agent de facturation
            statut='En attente'
        )
        db.session.add(nouvelle_facture)
        
        # Validation définitive de la transaction complète (Tout ou rien)
        db.session.commit()
        flash(f"✔ Transaction validée ! Facture unique {numero_unique_facture} émise avec succès !", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur système lors de l'écriture de la transaction : {str(e)}", "error")
        
    return redirect(url_for('suivi_ventes'))

@app.route('/ventes/supprimer/<int:id_vente>', methods=['POST'])
def supprimer_vente(id_vente):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    try:
        vente_principale = db.session.get(Vente, id_vente)
        if not vente_principale:
            flash("❌ Erreur : Vente introuvable.", "error")
            return redirect(url_for('liste_ventes'))

        # Sécurité : Restriction stricte sur le droit d'annulation
        utilisateur_connecte = Users.query.get(session['user_id'])
        est_admin = utilisateur_connecte.Fonction.lower() in ['administrateur', 'admin', 'gérant']
        
        if vente_principale.id_user != session['user_id'] and not est_admin:
            flash("❌ Action refusée : Vous n'êtes pas autorisé à annuler l'enregistrement d'un autre opérateur.", "error")
            return redirect(url_for('liste_ventes'))

        # 1. Restitution complète des stocks physiques
        liaisons = db.session.query(vente_produit).filter_by(id_vente=id_vente).all()
        for liaison in liaisons:
            produit_cible = db.session.get(Produit, liaison.id_produit)
            if produit_cible:
                produit_cible.stock += int(liaison.quantite)

        # 2. Nettoyage en cascade des factures et règlements associés
        facture_associee = Facture.query.filter_by(id_vente=id_vente).first()
        if facture_associee:
            db.session.query(Paiement).filter_by(id_facture=facture_associee.id_facture).delete()
            db.session.delete(facture_associee)

        # 3. Suppression dans la table d'association et suppression de la vente principale
        db.session.execute(vente_produit.delete().where(vente_produit.c.id_vente == id_vente))
        db.session.delete(vente_principale)
        db.session.commit()
        
        flash("✔ La vente a été annulée avec succès, sa facture supprimée et le stock réajusté !", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la suppression de la vente : {str(e)}", "error")
        
    return redirect(url_for('suivi_ventes'))

# -------------------------------------------------------
# FACTURES 
# -------------------------------------------------------
@app.route('/factures', methods=['GET'])
def liste_factures():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    try:
        utilisateur_connecte = Users.query.get(session['user_id'])
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        est_admin_ou_comptable = fonction_user in roles_superieurs
        
        maintenant = datetime.now()
        mois_selectionne = request.args.get('filter_mois', maintenant.strftime('%m'))
        annee_selectionnee = request.args.get('filter_annee', maintenant.strftime('%Y'))
        
        # PARAMÈTRE DE PAGINATION DYNAMIQUE
        page = request.args.get('page', 1, type=int)
        par_page = 50  # Limite stricte d'affichage par écran pour garantir la fluidité

        sous_req_montant_vente = db.session.query(
            vente_produit.c.id_vente,
            func.sum(vente_produit.c.quantite * vente_produit.c.prix_unitaire).label('total_facture')
        ).group_by(vente_produit.c.id_vente).subquery()
        
        sous_req_paiements = db.session.query(
            Paiement.id_facture,
            func.sum(Paiement.montant).label('total_paye')
        ).group_by(Paiement.id_facture).subquery()
        
        # Ajout de joinedload pour optimiser l'extraction des modèles liés à la facture
        query_factures = db.session.query(
            Facture,
            func.coalesce(sous_req_montant_vente.c.total_facture, 0.0).label('montant_vente'),
            func.coalesce(sous_req_paiements.c.total_paye, 0.0).label('montant_paye')
        ).options(joinedload(Facture.client), joinedload(Facture.operateur))\
         .outerjoin(sous_req_montant_vente, Facture.id_vente == sous_req_montant_vente.c.id_vente)\
         .outerjoin(sous_req_paiements, Facture.id_facture == sous_req_paiements.c.id_facture)\
         .join(Client, Facture.id_client == Client.id_client)
         
        if mois_selectionne:
            query_factures = query_factures.filter(extract('month', Facture.date_facture) == int(mois_selectionne))
        if annee_selectionnee:
            query_factures = query_factures.filter(extract('year', Facture.date_facture) == int(annee_selectionnee))
            
        if not est_admin_ou_comptable:
            query_factures = query_factures.filter(Facture.id_user == session['user_id'])
            
        # APPLICATION DU SYSTÈME DE PAGINATION NATIVE SQL
        pagination = query_factures.order_by(Facture.date_facture.desc(), Facture.id_facture.desc()).paginate(
            page=page, per_page=par_page, error_out=False
        )
        
        factures_formatees = []
        total_facture_global = 0.0
        total_encaisses_global = 0.0
        
        # Parcourir uniquement les éléments de la page en cours
        for f, montant_facture, total_deja_paye in pagination.items:
            reste_a_payer = montant_facture - total_deja_paye
            total_facture_global += montant_facture
            total_encaisses_global += total_deja_paye
            
            factures_formatees.append({
                'id_facture': f.id_facture,
                'numero_facture': f.numero_facture,
                'date_brute': f.date_facture.strftime('%d/%m/%Y') if f.date_facture else '-',
                'nom_client': f.client.nom if f.client else "Client Tout-venant",
                'montant_total': round(montant_facture, 0),
                'total_paye': round(total_deja_paye, 0),
                'reste_payer': round(reste_a_payer, 0),
                'statut': f.statut or 'En attente',
                'operateur': f.operateur.NomUtilisateur if f.operateur else 'Système'
            })
            
        total_creances = total_facture_global - total_encaisses_global
        config = Configuration.query.first()
        
        donnees_entreprise = {
            'raison_sociale': config.raison_sociale if (config and config.raison_sociale) else "Exploitation Avicole",
            'adresse': config.adresse if (config and config.adresse) else "Ferme d'Élevage",
            'telephone': config.telephone if (config and config.telephone) else "Contact Admin",
            'logo': config.logo if (config and config.logo) else None
        }
        
        liste_annees = [int(a[0]) for a in db.session.query(extract('year', Facture.date_facture).distinct()).all() if a[0] is not None]
        if int(annee_selectionnee) not in liste_annees:
            liste_annees.append(int(annee_selectionnee))
            
        return render_template(
            'suivifactures.html', factures=factures_formatees, total_facture=round(total_facture_global, 0),
            total_encaisses=round(total_encaisses_global, 0), total_creances=round(total_creances, 0),
            entreprise=donnees_entreprise, annees=sorted(liste_annees, reverse=True),
            mois_sel=mois_selectionne, annee_sel=annee_selectionnee, pagination=pagination
        )
    except Exception as e:
        db.session.rollback()
        return f"<h3>Erreur de chargement du facturier :</h3><p>{str(e)}</p>"
# =======================================================================
# MODULE : ENCAISSEMENTS & JOURNAL DE CAISSE (ULTRA-RAPIDE & PAGINÉ)
# =======================================================================

@app.route('/paiements', methods=['GET', 'POST'])
def gestion_paiements_page():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # 1. SÉCURITÉ COMPLÈTE : Audit du rôle utilisateur connecté
        utilisateur_connecte = Users.query.get(session['user_id'])
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        roles_autorises = roles_superieurs + ['caissier', 'caissière']
        
        if fonction_user not in roles_autorises:
            flash("Accès refusé : Droits insuffisants pour accéder au guichet.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs

        # =================================================================
        # TRAITEMENT DE L'ENCAISSEMENT EN CAISSE (MÉTHODE POST)
        # =================================================================
        if request.method == 'POST':
            id_facture_str = request.form.get('id_facture')
            montant_verse_str = request.form.get('montant')
            mode_paiement = request.form.get('mode_paiement')
            date_str = request.form.get('date_paiement')
            
            if not all([id_facture_str, montant_verse_str, mode_paiement, date_str]):
                flash("❌ Erreur : Veuillez remplir tous les champs obligatoires.", "error")
                return redirect(url_for('gestion_paiements_page'))
                
            id_facture = int(id_facture_str)
            montant_verse = float(montant_verse_str or 0)
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()
            
            facture_cible = db.session.get(Facture, id_facture)
            if not facture_cible:
                flash("❌ Erreur : La facture sélectionnée est introuvable.", "error")
                return redirect(url_for('gestion_paiements_page'))
                
            # CLOISONNEMENT STRICT : Le caissier ne peut pas encaisser une facture d'un autre agent
            if not est_admin_ou_comptable and facture_cible.id_user != session['user_id']:
                flash("❌ Action interdite : Vous ne pouvez pas encaisser cette facture.", "error")
                return redirect(url_for('gestion_paiements_page'))
                
            # Calculs comptables anti-surpaiement
            produits_vendus = db.session.query(vente_produit.c.quantite, vente_produit.c.prix_unitaire)\
                .filter(vente_produit.c.id_vente == facture_cible.id_vente).all()
            montant_total_facture = sum(float(q or 0) * float(p or 0) for q, p in produits_vendus)
            
            total_deja_paye = db.session.query(func.sum(Paiement.montant))\
                .filter(Paiement.id_facture == id_facture).scalar() or 0.0
            reste_a_payer_reel = montant_total_facture - total_deja_paye
            
            if montant_verse > (reste_a_payer_reel + 0.1):
                flash(f"❌ Saisie refusée : Le montant dépasse le reste dû ({int(reste_a_payer_reel):,} FCFA).", "error")
                return redirect(url_for('gestion_paiements_page'))
                
            # Enregistrement du paiement
            nouveau_paiement = Paiement(
                id_facture=id_facture,
                montant=montant_verse,
                mode_paiement=mode_paiement,
                date_paiement=date_obj,
                id_user=session['user_id']
            )
            db.session.add(nouveau_paiement)
            db.session.flush()
            
            # Recalcul dynamique du statut de la facture
            total_encaisse_mis_a_jour = total_deja_paye + montant_verse
            if total_encaisse_mis_a_jour >= (montant_total_facture - 0.1):
                facture_cible.statut = 'Payée'
            elif total_encaisse_mis_a_jour > 0:
                facture_cible.statut = 'Partielle'
            else:
                facture_cible.statut = 'En attente'
                
            db.session.commit()
            flash(f"✔ Règlement de {int(montant_verse):,} FCFA enregistré avec succès !", "success")
            return redirect(url_for('gestion_paiements_page'))

        # =================================================================
        # RENDU VISUEL ET FILTRAGE DU JOURNAL DE CAISSE (MÉTHODE GET)
        # =================================================================
        page = request.args.get('page', 1, type=int)
        par_page = 40  # Seuil optimal pour affichage instantané
        
        maintenant = datetime.now()
        mois_selectionne = request.args.get('filter_mois', maintenant.strftime('%m'))
        annee_selectionnee = request.args.get('filter_annee', maintenant.strftime('%Y'))
        client_selectionne = request.args.get('filter_client', '')
        
        # Requête de base optimisée (Jointures explicites rapides)
        base_query = db.session.query(
            Paiement.id_paiement,
            Paiement.id_facture,
            Paiement.date_paiement,
            Paiement.montant,
            Paiement.mode_paiement,
            Facture.numero_facture,
            Client.nom.label('nom_client'),
            Users.NomUtilisateur.label('nom_operateur')
        ).join(Facture, Paiement.id_facture == Facture.id_facture)\
         .join(Client, Facture.id_client == Client.id_client)\
         .join(Users, Paiement.id_user == Users.NumUser)
         
        # Application des filtres natifs
        if mois_selectionne:
            base_query = base_query.filter(extract('month', Paiement.date_paiement) == int(mois_selectionne))
        if annee_selectionnee:
            base_query = base_query.filter(extract('year', Paiement.date_paiement) == int(annee_selectionnee))
        if client_selectionne:
            base_query = base_query.filter(Client.nom == client_selectionne)
            
        # CLOISONNEMENT HISTORIQUE STRICT : Le caissier ne voit QUE ses propres recettes
        if not est_admin_ou_comptable:
            base_query = base_query.filter(Paiement.id_user == session['user_id'])
            factures_ouvertes = Facture.query.filter(Facture.statut.in_(['En attente', 'Partielle'])).filter_by(id_user=session['user_id']).all()
        else:
            factures_ouvertes = Facture.query.filter(Facture.statut.in_(['En attente', 'Partielle'])).all()
            
        # Exécution paginée de la requête principale
        pagination = base_query.order_by(Paiement.date_paiement.desc(), Paiement.id_paiement.desc()).paginate(
            page=page, per_page=par_page, error_out=False
        )
        
        # Calcul du total des recettes (uniquement sur le périmètre autorisé)
        sum_query = db.session.query(func.sum(Paiement.montant)).filter(
            extract('month', Paiement.date_paiement) == int(mois_selectionne),
            extract('year', Paiement.date_paiement) == int(annee_selectionnee)
        )
        if not est_admin_ou_comptable:
            sum_query = sum_query.filter(Paiement.id_user == session['user_id'])
        if client_selectionne:
            sum_query = sum_query.join(Facture).join(Client).filter(Client.nom == client_selectionne)
            
        total_ca_encaisse = sum_query.scalar() or 0.0

        # Menu déroulant intelligent des factures dues (Anti-requêtes N+1)
        id_factures_ouvertes = [fac.id_facture for fac in factures_ouvertes]
        liste_factures_select = []
        if id_factures_ouvertes:
            sous_req_v = db.session.query(vente_produit.c.id_vente, func.sum(vente_produit.c.quantite * vente_produit.c.prix_unitaire).label('total_f')).group_by(vente_produit.c.id_vente).subquery()
            sous_req_p = db.session.query(Paiement.id_facture, func.sum(Paiement.montant).label('total_p')).group_by(Paiement.id_facture).subquery()
            stats_factures = db.session.query(Facture.id_facture, Facture.numero_facture, Client.nom, func.coalesce(sous_req_v.c.total_f, 0.0), func.coalesce(sous_req_p.c.total_p, 0.0))\
                .outerjoin(sous_req_v, Facture.id_vente == sous_req_v.c.id_vente).outerjoin(sous_req_p, Facture.id_facture == sous_req_p.c.id_facture).join(Client, Facture.id_client == Client.id_client).filter(Facture.id_facture.in_(id_factures_ouvertes)).all()
                
            for id_f, num_f, client_nom, total_fac, total_p in stats_factures:
                reste = total_fac - total_p
                if reste > 0.1:
                    liste_factures_select.append({'id_facture': id_f, 'libelle': f"{num_f} - {client_nom} (Reste : {int(reste):,} FCFA)"})

        # Extraction sécurisée des listes de filtres (Zéro objet Row)
        annees_dispo = db.session.query(extract('year', Paiement.date_paiement).distinct()).all()
        liste_annees = [int(a[0]) for a in annees_dispo if a and a[0] is not None]
        if int(annee_selectionnee) not in liste_annees:
            liste_annees.append(int(annee_selectionnee))
            
        clients_dispo = db.session.query(Client.nom).distinct().order_by(Client.nom).all()
        liste_clients = [c[0] for c in clients_dispo if c and c[0] is not None]

        return render_template(
            'suivipaiements.html',
            paiements=pagination.items,
            pagination=pagination,
            factures_disponibles=liste_factures_select,
            total_ca_encaisse=round(total_ca_encaisse, 0),
            liste_annees=sorted(liste_annees, reverse=True),
            liste_clients=liste_clients,
            mois_sel=mois_selectionne,
            annee_sel=annee_selectionnee,
            client_sel=client_selectionne
        )

    except Exception as e:
        db.session.rollback()
        return f"<h3>❌ Erreur lors du chargement du module de paiement :</h3> <p>{str(e)}</p>"

#.............................................
# Facture clients
#............................................
def nombre_en_lettres(montant):
    """Fonction de conversion locale des montants en lettres (Français)"""
    if montant == 0:
        return "zéro"
    
    unites = ["", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf"]
    dizaines = ["", "dix", "vingt", "trente", "quarante", "cinquante", "soixante", "soixante-dix", "quatre-vingt", "quatre-vingt-dix"]
    entre_10_20 = ["dix", "onze", "douze", "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
    
    def convertir_bloc(n):
        if n == 0:
            return ""
        c = n // 100
        d = (n % 100) // 10
        u = n % 10
        res = []
        
        if c > 0:
            if c == 1:
                res.append("cent")
            else:
                res.append(unites[c] + " cent")
        
        if d == 1:
            res.append(entre_10_20[u])
        elif d > 1:
            if d == 7 and u > 0:
                res.append("soixante et " + entre_10_20[u] if u == 1 else "soixante-" + entre_10_20[u])
            elif d == 9 and u > 0:
                res.append("quatre-vingt-" + entre_10_20[u])
            else:
                if u == 1 and d != 8:
                    res.append(dizaines[d] + " et un")
                elif u > 0:
                    res.append(dizaines[d] + "-" + unites[u])
                else:
                    res.append(dizaines[d])
        elif u > 0:
            res.append(unites[u])
            
        return " ".join(res)

    milliards = montant // 1000000000
    millions = (montant % 1000000000) // 1000000
    milliers = (montant % 1000000) // 1000
    reste = montant % 1000
    
    resultat = []
    if milliards > 0:
        resultat.append(convertir_bloc(milliards) + " milliard" + ("s" if milliards > 1 else ""))
    if millions > 0:
        resultat.append(convertir_bloc(millions) + " million" + ("s" if millions > 1 else ""))
    if milliers > 0:
        if milliers == 1:
            resultat.append("mille")
        else:
            resultat.append(convertir_bloc(milliers) + " mille")
    if reste > 0:
        resultat.append(convertir_bloc(reste))
        
    return " ".join(resultat).strip()

##.............................................
# Foormat de la facture à imprimer
#............................................

@app.route('/factures/telecharger_a5/<int:id_facture>', methods=['GET'])
def generer_facture_pdf_a5(id_facture):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    facture = db.session.get(Facture, id_facture)
    if not facture:
        flash("❌ Facture introuvable.", "error")
        return redirect(url_for('gestion_paiements_page'))
        
    client = facture.client
    config = Configuration.query.first()
    nom_entreprise = config.raison_sociale if (config and config.raison_sociale) else "PROMAS"
    adresse_entreprise = config.adresse if (config and config.adresse) else "Parcelles Assainies"
    contact_entreprise = f"Tél: {config.telephone}" if (config and config.telephone) else "Tél: N/A"
    email_entreprise = f"Email: {config.email}" if (config and hasattr(config, 'email') and config.email) else "Email: biayemartin7@gmail.com"
    ninea_str = config.ninea if (config and config.ninea) else "0111239820"
    rccm_str = config.rccm if (config and config.rccm) else "SN DKR 2024 A 20001"
    logo_filename = config.logo if (config and config.logo) else None
    
    produits_vendus = db.session.query(
        Produit.designation.label('nom_produit'),
        Produit.unite.label('unite_produit'),
        vente_produit.c.quantite.label('qte'),
        vente_produit.c.prix_unitaire.label('pu')
    ).join(Produit, vente_produit.c.id_produit == Produit.id_produit)\
     .filter(vente_produit.c.id_vente == facture.id_vente).all()
     
    total_paye = db.session.query(func.sum(Paiement.montant)).filter(Paiement.id_facture == id_facture).scalar() or 0.0
    montant_total = sum(float(p.qte or 0) * float(p.pu or 0) for p in produits_vendus)
    reste_a_payer = montant_total - float(total_paye)

    buffer = io.BytesIO()
    
    # Pied de page fiscal compact pour le format A5
    def ajouter_pied_de_page_a5(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setStrokeColor(colors.HexColor("#333333"))
        canvas.line(30, 30, 560, 30)
        texte_fiscal = f"NINEA : {ninea_str}   |   RCCM : {rccm_str}   |   PROMAS - Parcelles Assainies"
        canvas.drawCentredString(295, 18, texte_fiscal)
        canvas.restoreState()

    # Définition des marges à 30 points pour optimiser le format A5 Paysage
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A5), rightMargin=30, leftMargin=30, topMargin=25, bottomMargin=45)
    story = []
    
    styles = getSampleStyleSheet()
    style_normal = styles['Normal']
    
    style_comptable = ParagraphStyle('A5Style', parent=style_normal, fontName='Helvetica', fontSize=9, leading=12, textColor=colors.HexColor("#1e2229"))
    style_comptable_bold = ParagraphStyle('A5StyleBold', parent=style_comptable, fontName='Helvetica-Bold')
    style_center_bold = ParagraphStyle('A5CenterBold', parent=style_comptable_bold, alignment=1)
    style_right_bold = ParagraphStyle('A5RightBold', parent=style_comptable_bold, alignment=2)
    style_logo_text = ParagraphStyle('A5LogoText', parent=style_normal, fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=1)
    style_titre_facture = ParagraphStyle('A5TitreFacture', parent=style_normal, fontName='Helvetica-Bold', fontSize=16, leading=20, alignment=1)

    # --- BLOC 1 : EN-TÊTE COMPACT BORNÉ ET ALIGNÉ SUR 530 POINTS ---
    texte_ferme = f"<b>{nom_entreprise.upper()}</b><br/>{adresse_entreprise} | {contact_entreprise}<br/>{email_entreprise}"
    
    logo_inclu = False
    if logo_filename:
        chemin_logo = os.path.join(current_app.root_path, 'static', 'uploads', logo_filename)
        if not os.path.exists(chemin_logo):
            chemin_logo = os.path.join(current_app.root_path, 'static', logo_filename)
        if os.path.exists(chemin_logo):
            try:
                cellule_logo = RLImage(chemin_logo, width=45, height=45) # Échelle A5
                logo_inclu = True
            except Exception:
                logo_inclu = False
            
    if not logo_inclu:
        cellule_logo = Paragraph("<b>LOGO<br/>PROMAS</b>", style_logo_text)
        
    entete_table = Table([[Paragraph(texte_ferme, style_comptable), cellule_logo]], colWidths=[430, 100])
    entete_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (0,0), 10),
        ('RIGHTPADDING', (1,0), (1,0), 10),
    ]))
    story.append(entete_table)
    story.append(Spacer(1, 8))
    
    # --- BLOC 2 : BANDEAU « FACTURE » ---
    titre_table = Table([[Paragraph("FACTURE", style_titre_facture)]], colWidths=[530])
    titre_table.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 1.2, colors.black),
        ('PADDING', (0,0), (-1,-1), 4),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    story.append(titre_table)
    story.append(Spacer(1, 8))
    
       # --- BLOC 3 : INFOS CLIENT (CORRIGÉ) ---
    date_facture_str = facture.date_facture.strftime('%d/%m/%Y') if hasattr(facture, 'date_facture') and facture.date_facture else 'N/A'
    nom_client = client.nom if client else "Client Tout-venant"
    
    # ⬇ CRÉATION ET DÉFINITION DE LA VARIABLE MANQUANTE ICI ⬇
        # CORRECTION : Utilisation correcte de la fonction native hasattr(objet, 'attribut')
    tel_client = client.telephone if client and hasattr(client, 'telephone') else "-"

    info_gauche = f"<b>Facture N° :</b> {facture.numero_facture}  |  <b>Date :</b> {date_facture_str}"
    info_droite = f"<b>Client :</b> {nom_client}  |  <b>Tél :</b> {tel_client}"
    
    info_table = Table([[Paragraph(info_gauche, style_comptable), Paragraph(info_droite, style_comptable)]], colWidths=[265, 265])
    info_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('PADDING', (0,0), (-1,-1), 1)]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    
    # --- BLOC 4 : TABLEAU DES ARTICLES ---
    table_content = [[
        Paragraph("<b>DESIGNATION / ARTICLE</b>", style_comptable_bold),
        Paragraph("<b>QTE</b>", style_center_bold),
        Paragraph("<b>UNITE</b>", style_center_bold),
        Paragraph("<b>P. UNITAIRE (FCFA)</b>", style_center_bold),
        Paragraph("<b>TOTAL (FCFA)</b>", style_center_bold)
    ]]
    
    for item in produits_vendus:
        total_ligne = float(item.qte or 0) * float(item.pu or 0)
        table_content.append([
            Paragraph(item.nom_produit, style_comptable),
            Paragraph(f"{int(item.qte)}", style_center_bold),
            Paragraph(item.unite_produit or "U", style_center_bold),
            Paragraph(f"{int(item.pu):,}".replace(',', ' '), style_center_bold),
            Paragraph(f"{int(total_ligne):,}".replace(',', ' '), style_center_bold)
        ])
        
    table_content.append([
        Paragraph("<b>TOTAL GENERAL</b>", style_comptable_bold), "", "", "",
        Paragraph(f"<b>{int(montant_total):,} FCFA</b>".replace(',', ' '), style_center_bold)
    ])
    
    # Grille totale = 530 points (230 + 45 + 55 + 100 + 100)
    item_table = Table(table_content, colWidths=[230, 45, 55, 100, 100])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#eef2f5")),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('SPAN', (0, -1), (3, -1)),
        ('ALIGN', (1,1), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 10))
    
    # --- BLOC 5 : SITUATION FINANCIÈRE RE-ALIGNÉE ---
    situation_data = [
        [Paragraph("<b>MONTANT TOTAL DE LA FACTURE :</b>", style_comptable), Paragraph(f"<b>{int(montant_total):,} FCFA</b>".replace(',', ' '), style_center_bold)],
        [Paragraph("<b>MONTANT DEJA ENCAISSE :</b>", style_comptable), Paragraph(f"<b>{int(total_paye):,} FCFA</b>".replace(',', ' '), style_center_bold)],
        [Paragraph("<b>NET A PAYER (RESTE) :</b>", style_comptable_bold), Paragraph(f"<b>{int(reste_a_payer):,} FCFA</b>".replace(',', ' '), style_center_bold)]
    ]
    
    situation_table = Table(situation_data, colWidths=[330, 200])
    situation_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('PADDING', (0,0), (-1,-1), 5),
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(situation_table)
    story.append(Spacer(1, 10))
    
    # --- BLOC 6 : ARRET COMPTABLE ---
    montant_lettres_paye = nombre_en_lettres(int(total_paye))
    phrase_arrete = f"<u>Arrêté la présente facture à la somme de :</u> {nombre_en_lettres(int(montant_total))} Francs CFA (dont <b>{montant_lettres_paye} F CFA</b> encaissés)."
    story.append(Paragraph(phrase_arrete, style_comptable))
    
    doc.build(story, onFirstPage=ajouter_pied_de_page_a5, onLaterPages=ajouter_pied_de_page_a5)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=False, mimetype='application/pdf')

##.............................................
# Foormat du reçu à imprimer
#............................................
    
@app.route('/paiements/telecharger_ticket_80mm/<int:id_paiement>', methods=['GET'])
def generer_recu_ticket_80mm(id_paiement):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    paiement = db.session.get(Paiement, id_paiement)
    if not paiement:
        flash("❌ Enregistrement de règlement introuvable.", "error")
        return redirect(url_for('gestion_paiements_page'))
        
    facture = paiement.facture
    client = facture.client
    config = Configuration.query.first()
    nom_entreprise = config.raison_sociale if (config and config.raison_sociale) else "PROMAS"
    contact_entreprise = f"Tél: {config.telephone}" if (config and config.telephone) else "Tél: N/A"
    ninea_str = config.ninea if (config and config.ninea) else "0111239820"

    buffer = io.BytesIO()
    
    # Largeur fixe de 80mm (environ 226 points) et hauteur ajustable de 400 points
    largeur_ticket = 226
    doc = SimpleDocTemplate(buffer, pagesize=(largeur_ticket, 400), rightMargin=8, leftMargin=8, topMargin=8, bottomMargin=8)
    story = []
    
    styles = getSampleStyleSheet()
    style_normal = styles['Normal']
    
    # Styles minis adaptés au format ticket de caisse
    style_ticket = ParagraphStyle('TicketStyle', parent=style_normal, fontName='Helvetica', fontSize=8, leading=10, textColor=colors.HexColor("#1e2229"))
    style_ticket_bold = ParagraphStyle('TicketStyleBold', parent=style_ticket, fontName='Helvetica-Bold')
    style_ticket_center = ParagraphStyle('TicketStyleCenter', parent=style_ticket_bold, alignment=1)
    style_ticket_right = ParagraphStyle('TicketStyleRight', parent=style_ticket_bold, alignment=2)

    # --- ENTÊTE COMPACT ---
    story.append(Paragraph(f"<b>*** {nom_entreprise.upper()} ***</b>", style_ticket_center))
    story.append(Paragraph(f"Parcelles Assainies | {contact_entreprise}", style_ticket_center))
    story.append(Paragraph(f"NINEA : {ninea_str}", style_ticket_center))
    story.append(Spacer(1, 5))
    story.append(Paragraph("--------------------------------------------------", style_ticket_center))
    story.append(Paragraph("<b>TICKET DE PAIEMENT</b>", style_ticket_center))
    story.append(Paragraph("--------------------------------------------------", style_ticket_center))
    
    # --- INFOS TRANSACTION ---
    date_p_str = paiement.date_paiement.strftime('%d/%m/%Y') if hasattr(paiement, 'date_paiement') and paiement.date_paiement else 'N/A'
    story.append(Paragraph(f"<b>Date :</b> {date_p_str}", style_ticket))
    story.append(Paragraph(f"<b>Ticket N° :</b> REC-{paiement.id_paiement}", style_ticket))
    story.append(Paragraph(f"<b>Ref Facture :</b> {facture.numero_facture}", style_ticket))
    story.append(Paragraph(f"<b>Client :</b> {client.nom if client else 'Tout-venant'}", style_ticket))
    story.append(Spacer(1, 5))
    
    # --- TABLEAU DE CAISSE MINI ---
    table_content = [
        [Paragraph("<b>Libellé / Mode</b>", style_ticket_bold), Paragraph("<b>Montant</b>", style_ticket_right)]
    ]
    libelle_p = f"Acompte Fac {facture.numero_facture}<br/>Mode: {paiement.mode_paiement or 'Espèces'}"
    table_content.append([
        Paragraph(libelle_p, style_ticket),
        Paragraph(f"<b>{int(paiement.montant):,}</b>".replace(',', ' '), style_ticket_right)
    ])
    
    # Largeur totale max disponible = 210 points
    ticket_table = Table(table_content, colWidths=[130, 80])
    ticket_table.setStyle(TableStyle([
        ('LINEBELOW', (0,0), (-1,0), 0.5, colors.black),
        ('LINEBELOW', (0,-1), (-1,-1), 0.5, colors.black),
        ('PADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(ticket_table)
    story.append(Spacer(1, 8))
    
    # --- LE NET EN TOUTES LETTRES ---
    montant_lettres = nombre_en_lettres(int(paiement.montant))
    story.append(Paragraph(f"<i>Arrêté à : {montant_lettres} F CFA.</i>", style_ticket))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Merci de votre confiance !", style_ticket_center))
    
    doc.build(story)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=False, mimetype='application/pdf')

# ... Votre fonction nombre_en_lettres reste disponible au-dessus ...

@app.route('/factures/telecharger/<int:id_facture>', methods=['GET'])
def generer_facture_pdf(id_facture):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    # 1. Extraction sécurisée de la facture depuis PostgreSQL
    facture = db.session.get(Facture, id_facture)
    if not facture:
        flash("❌ Facture introuvable.", "error")
        return redirect(url_for('liste_factures'))
        
    # 2. SÉCURITÉ CLOISONNEMENT : Vérification du profil connecté
    utilisateur_connecte = db.session.get(Users, session['user_id'])
    est_admin = utilisateur_connecte.Fonction.lower() in ['administrateur', 'admin', 'gérant']
    
    if facture.id_user != session['user_id'] and not est_admin:
        flash("❌ Accès refusé : Vous n'êtes pas autorisé à télécharger ce document.", "error")
        return redirect(url_for('liste_factures'))

    # 3. Extraction des mentions de configuration de l'établissement
    config = Configuration.query.first()
    raison_sociale = config.raison_sociale if (config and config.raison_sociale) else "PROMAS"
    adresse_entreprise = config.adresse if (config and config.adresse) else "Parcelles Assainies"
    telephone_entreprise = config.telephone if (config and config.telephone) else ""
    email_entreprise = config.email if (config and hasattr(config, 'email') and config.email) else "biayemartin7@gmail.com"
    ninea_str = config.ninea if (config and config.ninea) else "0111239820"
    rccm_str = config.rccm if (config and config.rccm) else "SN DKR 2024 A 20001"
    logo_filename = config.logo if (config and config.logo) else None

    # 4. Extraction des lignes d'articles vendus via la table d'association
    produits_vendus = db.session.query(
        Produit.designation.label('nom_produit'),
        Produit.unite.label('unite_produit'),
        vente_produit.c.quantite.label('qte'),
        vente_produit.c.prix_unitaire.label('pu')
    ).join(Produit, vente_produit.c.id_produit == Produit.id_produit)\
     .filter(vente_produit.c.id_vente == facture.id_vente).all()

    # 5. Calculs financiers
    total_paye = db.session.query(func.sum(Paiement.montant)).filter(Paiement.id_facture == id_facture).scalar() or 0.0
    montant_total = sum(float(p.qte or 0) * float(p.pu or 0) for p in produits_vendus)
    reste_a_payer = montant_total - float(total_paye)

    buffer = io.BytesIO()

    # 6. Tracé du pied de page fiscal pour le format A4 Portrait
    def ajouter_pied_de_page_a4(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.setStrokeColor(colors.HexColor("#dddddd"))
        canvas.line(36, 45, 559, 45)
        texte_fiscal = f"NINEA : {ninea_str}   |   RCCM : {rccm_str}   |   {raison_sociale} - {adresse_entreprise}"
        canvas.drawCentredString(297.5, 30, texte_fiscal)
        canvas.restoreState()

    # 7. Configuration du canevas ReportLab
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=40, bottomMargin=65)
    story = []
    styles = getSampleStyleSheet()
    
    style_normal = styles['Normal']
    style_facture = ParagraphStyle('A4Facture', parent=style_normal, fontName='Helvetica', fontSize=10, leading=14, textColor=colors.HexColor("#1e2229"))
    style_facture_bold = ParagraphStyle('A4FactureBold', parent=style_facture, fontName='Helvetica-Bold')
    
    style_th_sombre = ParagraphStyle('THSombre', parent=style_facture_bold, textColor=colors.HexColor('#1e2229'))
    style_th_sombre_center = ParagraphStyle('THSombreCenter', parent=style_th_sombre, alignment=1)
    
    style_center_bold = ParagraphStyle('A4CenterBold', parent=style_facture_bold, alignment=1)
    style_right = ParagraphStyle('A4Right', parent=style_facture, alignment=2)
    style_logo_text = ParagraphStyle('A4LogoText', parent=style_normal, fontName='Helvetica-Bold', fontSize=12, leading=14, alignment=1)

    # --- BLOCK EN-TÊTE BORNÉ DYNAMIQUE AVEC LOGO ---
    texte_entreprise = f"<b>{raison_sociale.upper()}</b><br/>{adresse_entreprise}<br/>Tél: {telephone_entreprise}<br/>{email_entreprise}"
    cellule_logo = Paragraph("<b>LOGO<br/>PROMAS</b>", style_logo_text)
    
    if logo_filename:
        chemin_logo = os.path.join(current_app.root_path, 'static', 'uploads', logo_filename)
        if not os.path.exists(chemin_logo):
            chemin_logo = os.path.join(current_app.root_path, 'static', logo_filename)
        if os.path.exists(chemin_logo):
            try:
                cellule_logo = RLImage(chemin_logo, width=65, height=65)
            except Exception:
                pass

    header_table = Table([[Paragraph(texte_entreprise, style_facture), cellule_logo]], colWidths=[440, 100])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#1e2229')), 
        ('PADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 15))

    # Cartouche d'informations Facture / Coordonnées Client
    date_facture_str = facture.date_facture.strftime('%d/%m/%Y') if facture.date_facture else 'N/A'
    nom_client = facture.client.nom if facture.client else "Client Tout-venant"
    tel_client = facture.client.telephone if (facture.client and facture.client.telephone) else "-"
    adresse_client = facture.client.adresse if (facture.client and facture.client.adresse) else "-"

    table_infos = Table([
        [Paragraph(f"<font size=14 color='#1e2229'><b>FACTURE N° {facture.numero_facture}</b></font><br/><br/><b>Date d'Émission :</b> {date_facture_str}", style_facture),
         Paragraph(f"<b>CLIENT :</b><br/><b>Nom :</b> {nom_client}<br/><b>Tél :</b> {tel_client}<br/><b>Adresse :</b> {adresse_client}", style_facture)]
    ], colWidths=[270, 270])
    
    table_infos.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#f8f9fa')),
        ('BACKGROUND', (1,0), (1,0), colors.HexColor('#f4f6f9')),
        ('BOX', (0,0), (0,0), 1, colors.HexColor('#dddddd')),
        ('BOX', (1,0), (1,0), 1, colors.HexColor('#cccccc')),
        ('PADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(table_infos)
    story.append(Spacer(1, 20))

    # --- GRILLE COMPTABLE HARMONISÉE ---
    table_content = [[
        Paragraph("<b>DÉSIGNATION DES ARTICLES</b>", style_th_sombre),
        Paragraph("<b>QTE</b>", style_th_sombre_center),
        Paragraph("<b>UNITÉ</b>", style_th_sombre_center),
        Paragraph("<b>P. UNITAIRE</b>", style_th_sombre_center),
        Paragraph("<b>MONTANT NET</b>", style_th_sombre_center)
    ]]
    
    for item in produits_vendus:
        total_ligne = float(item.qte or 0) * float(item.pu or 0)
        table_content.append([
            Paragraph(item.nom_produit, style_facture),
            Paragraph(f"{int(item.qte)}", style_center_bold),
            Paragraph(item.unite_produit or "U", style_center_bold),
            Paragraph(f"{int(item.pu):,}".replace(',', ' ') + " F", style_center_bold),
            Paragraph(f"{int(total_ligne):,}".replace(',', ' ') + " F", style_center_bold)
        ])
        
    table_content.append([Paragraph("<b>MONTANT TOTAL BRUT</b>", style_facture_bold), "", "", "", Paragraph(f"<b>{int(montant_total):,} FCFA</b>".replace(',', ' '), style_center_bold)])
    table_content.append([Paragraph("<b>MONTANT DÉJÀ VERSÉ (ACOMPTE)</b>", style_facture), "", "", "", Paragraph(f"{int(total_paye):,} FCFA".replace(',', ' '), style_center_bold)])
    table_content.append([Paragraph("<b>RESTE A RECOUVRER (SOLDE CRÉANCE)</b>", style_facture_bold), "", "", "", Paragraph(f"<b>{int(reste_a_payer):,} FCFA</b>".replace(',', ' '), style_center_bold)])
    
    item_table = Table(table_content, colWidths=[240, 45, 55, 100, 100])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f8f9fa")),
        ('GRID', (0,0), (-1,-4), 0.5, colors.HexColor('#aaaaaa')),
        ('GRID', (0,-3), (-1,-1), 1, colors.HexColor('#1e2229')),
        ('SPAN', (0, -3), (3, -3)),
        ('SPAN', (0, -2), (3, -2)),
        ('SPAN', (0, -1), (3, -1)),
        ('BACKGROUND', (0, -3), (-1, -3), colors.HexColor('#f8f9fa')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fce4d6')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 7),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 15))

    # Arrêt comptable en toutes lettres
    phrase_arrete = f"<b>Arrêtée la présente facture à la somme de :</b> {nombre_en_lettres(int(montant_total))} Francs CFA."
    story.append(Paragraph(phrase_arrete, style_facture))
    
    if total_paye > 0:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<i>Règlement : Somme de {nombre_en_lettres(int(total_paye))} Francs CFA reçue ce jour. Reste à percevoir : {int(reste_a_payer):,} FCFA.</i>", style_facture))
    
    story.append(Spacer(1, 30))

    # Signatures et validation de l'agent
    signature_data = [
        [Paragraph("<b>Le Responsable d'Exploitation</b><br/><br/><br/><i>Pour acquis et approbation</i>", style_facture),
         Paragraph(f"<b>Facturé par l'agent :</b><br/>@{facture.operateur.NomUtilisateur if facture.operateur else 'Système'}<br/><br/>Cachet PROMAS obligatoire", style_right)]
    ]
    signature_table = Table(signature_data, colWidths=[360, 180])
    signature_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(signature_table)

    # Compilation et envoi du fichier
    doc.build(story, onFirstPage=ajouter_pied_de_page_a4, onLaterPages=ajouter_pied_de_page_a4)
    buffer.seek(0)
    
    nom_facture_fichier = f"Facture_{facture.numero_facture}.pdf"
    return send_file(buffer, as_attachment=False, download_name=nom_facture_fichier, mimetype='application/pdf')


@app.route('/depenses', methods=['GET', 'POST'])
def gestion_depenses_page():
    # 1. SÉCURITÉ ET AUTHENTIFICATION EN SESSION
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # Récupération de l'utilisateur connecté pour valider ses privilèges
        utilisateur_connecte = Users.query.get(session['user_id'])
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        # Normalisation du rôle en minuscules pour éviter les erreurs de casse
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        
        # Définition des matrices d'autorisations PROMAS
        roles_autorises = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable', 'caissier', 'caissière']
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        
        # Barrière d'accès globale : Restreint l'entrée aux rôles non répertoriés
        if fonction_user not in roles_autorises:
            flash("❌ Accès refusé : Vous n'avez pas les privilèges requis pour accéder au suivi des dépenses.", "error")
            return redirect(url_for('index'))
            
        # Détermination de la hiérarchie pour le cloisonnement
        est_direction_ou_comptable = fonction_user in roles_superieurs

        # =================================================================
        # 2. ACTION D'ENREGISTREMENT (TRAITEMENT DU FORMULAIRE POST)
        # =================================================================
        if request.method == 'POST':
            id_depense_modif = request.form.get('id_depense_modif')
            type_depense_texte = request.form.get('id_type_depense', 'Autre')
            montant_str = request.form.get('montant')
            date_str = request.form.get('date_depense')
            commentaire_saisi = request.form.get('commentaire', '').strip()
            
            if not all([type_depense_texte, montant_str, date_str]):
                flash("❌ Erreur : Veuillez remplir tous les champs obligatoires du formulaire.", "error")
                return redirect(url_for('gestion_depenses_page'))
                
            montant = float(montant_str or 0.0)
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()
            type_propre = type_depense_texte.strip()
            commentaire_final = f"[{type_propre}] {commentaire_saisi}".strip()
            
            # Gestion ou création automatisée du poste de charge
            type_db = TypeDepense.query.filter(TypeDepense.libelle_type.ilike(type_propre)).first()
            if not type_db:
                type_db = TypeDepense(libelle_type=type_propre, description="Poste de charge", actif=True)
                db.session.add(type_db)
                db.session.flush()
                
            if id_depense_modif and id_depense_modif.strip() != "":
                # ─── MODE MODIFICATION SÉCURISÉ ───
                depense_existante = db.session.get(Depense, int(id_depense_modif))
                if depense_existante:
                    # Sécurité : Un caissier ne peut pas modifier un décaissement saisi par un autre agent
                    if not est_direction_ou_comptable and depense_existante.id_user != session['user_id']:
                        flash("❌ Action interdite : Vous ne pouvez pas modifier un décaissement saisi par un autre agent.", "error")
                        return redirect(url_for('gestion_depenses_page'))
                        
                    depense_existante.id_type_depense = type_db.id_type_depense
                    depense_existante.montant = montant
                    depense_existante.date_depense = date_obj
                    depense_existante.commentaire = commentaire_final
                    if hasattr(Depense, 'id_user'):
                        depense_existante.id_user = session['user_id']
                    flash(f"✔ Décaissement #{id_depense_modif} mis à jour avec succès !", "success")
                else:
                    flash("❌ Erreur : Enregistrement introuvable pour la modification.", "error")
            else:
                # ─── MODE AJOUT CLASSIQUE RÈGLEMENTAIRE ───
                nouvelle_depense = Depense(
                    id_type_depense=type_db.id_type_depense,
                    montant=montant,
                    date_depense=date_obj,
                    commentaire=commentaire_final
                )
                if hasattr(Depense, 'id_user'):
                    nouvelle_depense.id_user = session['user_id']
                db.session.add(nouvelle_depense)
                flash(f"✔ Décaissement enregistré avec succès !", "success")
                
            db.session.commit()
            return redirect(url_for('gestion_depenses_page'))

        # =================================================================
        # 3. RENDU ULTRA-RAPIDE ET FILTRAGE DE L'HISTORIQUE (GET)
        # =================================================================
        maintenant = datetime.now()
        mois_selectionne = request.args.get('filter_mois', maintenant.strftime('%m'))
        annee_selectionnee = request.args.get('filter_annee', maintenant.strftime('%Y'))
        page = request.args.get('page', 1, type=int)
        per_page = 20  # Utilisation d'un lot fixe pour une performance native SQL optimale

        # Construction de la requête avec jointure
        query_brute = db.session.query(Depense).join(TypeDepense)
        
        if mois_selectionne and mois_selectionne.isdigit():
            query_brute = query_brute.filter(extract('month', Depense.date_depense) == int(mois_selectionne))
        if annee_selectionnee and annee_selectionnee.isdigit():
            query_brute = query_brute.filter(extract('year', Depense.date_depense) == int(annee_selectionnee))
            
        # 🔒 CLOISONNEMENT SÉCURISÉ DES DONNÉES
        if est_direction_ou_comptable:
            # Les administrateurs et cadres supérieurs ont une vue globale
            pass
        else:
            # Les caissiers/caissières ne listent que leurs propres saisies
            if hasattr(Depense, 'id_user'):
                query_brute = query_brute.filter(Depense.id_user == session['user_id'])
                
        # Tri et exécution de la pagination native (SQL OFFSET / LIMIT)
        query_brute = query_brute.order_by(Depense.date_depense.desc())
        pagination = query_brute.paginate(page=page, per_page=per_page, error_out=False)
        enregistrements_sql = pagination.items
        
        entreprise_config = Configuration.query.first()
        liste_depenses_formatees = []
        total_charges_cumulees = 0.0
        
        # Traitement et restriction hiérarchique du calcul du total cumulé
        for item in enregistrements_sql:
            if est_direction_ou_comptable:
                total_charges_cumulees += float(item.montant or 0.0)
            else:
                if hasattr(item, 'id_user') and item.id_user == session['user_id']:
                    total_charges_cumulees += float(item.montant or 0.0)

            texte_brut_commentaire = item.commentaire or "Aucun détail"
            type_affiche = item.type_depense.libelle_type if item.type_depense else "Général"
            
            # Nettoyage propre du commentaire pour enlever l'ancien préfixe technique [Poste]
            if texte_brut_commentaire.startswith("[") and "]" in texte_brut_commentaire:
                parties = texte_brut_commentaire.split("]", 1)
                if len(parties) == 2:
                    texte_brut_commentaire = parties[1].strip()
                    
            nom_operateur = item.user.NomUtilisateur if (hasattr(item, 'user') and item.user) else "Système"
            
            class ElementFormate:
                def __init__(self, id_depense, date_depense, libelle_type, commentaire, montant, operateur):
                    self.id_depense = id_depense
                    self.date_depense = date_depense
                    self.libelle_type = libelle_type
                    self.commentaire = commentaire
                    self.montant = montant
                    self.operateur = operateur
                    
            liste_depenses_formatees.append(ElementFormate(
                id_depense=item.id_depense,
                date_depense=item.date_depense,
                libelle_type=type_affiche,
                commentaire=texte_brut_commentaire if texte_brut_commentaire else "Aucun détail",
                montant=int(float(item.montant or 0.0)),
                operateur=nom_operateur
            ))
            
        # Sécurisation du sélecteur d'années
        liste_annees_filtre = [maintenant.year]
        try:
            annees_extraites = db.session.query(extract('year', Depense.date_depense).distinct()).all()
            for row in annees_extraites:
                if row and row[0] is not None:
                    liste_annees_filtre.append(int(row[0]))
        except:
            pass
            
        if annee_selectionnee and annee_selectionnee.isdigit() and int(annee_selectionnee) not in liste_annees_filtre:
            liste_annees_filtre.append(int(annee_selectionnee))
            
        # Construction sémantique du texte de la période pour les impressions
        mois_traduction = {
            "01": "Janvier", "02": "Février", "03": "Mars", "04": "Avril",
            "05": "Mai", "06": "Juin", "07": "Juillet", "08": "Août",
            "09": "Septembre", "10": "Octobre", "11": "Novembre", "12": "Décembre"
        }

        cle_mois = mois_selectionne if mois_selectionne else maintenant.strftime('%m')
        cle_annee = annee_selectionnee if annee_selectionnee else str(maintenant.year)
        periode_texte_impression = f"{mois_traduction.get(cle_mois, 'Général')} / {cle_annee}"
        
        return render_template(
        'suividepenses.html',
        depenses=liste_depenses_formatees,
        pagination=pagination,
        total_charges=int(total_charges_cumulees),
        liste_annees=sorted(list(set(liste_annees_filtre)), reverse=True),
        mois_sel=mois_selectionne,
        annee_sel=annee_selectionnee,
        entreprise=entreprise_config,
        periode_impression=periode_texte_impression,
        est_admin=est_direction_ou_comptable # <-- Pilote l'affichage des éléments sensibles ou globaux
        )

    except Exception as e:
        db.session.rollback()
        return f"<h3>❌ Erreur de chargement de la page :</h3> <p>{str(e)}</p>"

# ==============================================================================
# 🛡️ RELATIONS ET DÉCLENCHEURS (HOOKS) AUTOMATIQUES DE GESTION DES STOCKS VÉTO
# ==============================================================================

@event.listens_for(Vaccination, 'after_insert')
def deduire_produit_veto_apres_soin(mapper, connection, target):
    """Soustrait automatiquement la quantité de produits vétérinaires consommée du stock produit"""
    try:
        qte_consommee = int(target.quantite_utilisee or 1)
        if qte_consommee > 0:
            connection.execute(
                db.text("UPDATE produit SET stock = stock - :qte WHERE id_produit = :id_prod"),
                {"qte": qte_consommee, "id_prod": target.id_produit}
            )
    except Exception:
        pass

@event.listens_for(Vaccination, 'before_update')
def réajuster_produit_veto_avant_modification(mapper, connection, target):
    """Réajuste le stock pharmacie si l'ouvrier modifie la quantité sur une fiche existante"""
    try:
        resultat = connection.execute(
            db.text("SELECT quantite_utilisee FROM vaccination WHERE id_vaccination = :id_vac"),
            {"id_vac": target.id_vaccination}
        ).fetchone()
        
        if resultat:
            ancienne_qte = int(resultat[0] if resultat[0] is not None else 1)
            nouvelle_qte = int(target.quantite_utilisee or 1)
            difference = nouvelle_qte - ancienne_qte
            
            if difference != 0:
                connection.execute(
                    db.text("UPDATE produit SET stock = stock - :diff WHERE id_produit = :id_prod"),
                    {"diff": difference, "id_prod": target.id_produit}
                )
    except Exception:
        pass

@event.listens_for(Vaccination, 'after_delete')
def restituer_produit_veto_apres_suppression(mapper, connection, target):
    """Restitue proprement les consommables au stock général si l'acte médical est annulé ou supprimé"""
    try:
        qte_a_rendre = int(target.quantite_utilisee or 1)
        if qte_a_rendre > 0:
            connection.execute(
                db.text("UPDATE produit SET stock = stock + :qte WHERE id_produit = :id_prod"),
                {"qte": qte_a_rendre, "id_prod": target.id_produit}
            )
    except Exception:
        pass

# ==============================================================================
# ⚙️ ROUTINES DE TRAITEMENT DES FLUX SANITAIRES (ROUTES FLASK)
# ==============================================================================

@app.route('/vaccinations', methods=['GET'])
def liste_vaccinations():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    try:
        # 1. Identification de l'opérateur connecté et de ses droits étendus
        user_id_connecte = session['user_id']
        utilisateur_connecte = Users.query.get(user_id_connecte)
        if not utilisateur_connecte:
            return redirect(url_for('connexion_get'))
            
        # Normalisation de la chaîne de caractères
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        
        # Définition des matrices de rôles PROMAS Aviculture
        roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        roles_ouvrier = ['ouvrier agricole', 'ouvrier', 'agent', 'technicien']
        
        est_admin = fonction_user in roles_admin
        est_ouvrier = fonction_user in roles_ouvrier
        
        # Sécurité globale : si le rôle n'existe pas dans le système
        if not est_admin and not est_ouvrier:
            flash("❌ Accès refusé : Votre profil n'est pas autorisé à consulter cette page.", "error")
            return redirect(url_for('index'))
            
        infos_entreprise = Configuration.query.first()
        
        # Filtres temporels par défaut
        maintenant = datetime.now()
        mois_selectionne = request.args.get('filter_mois', maintenant.strftime('%m'))
        annee_selectionnee = request.args.get('filter_annee', maintenant.strftime('%Y'))
        lot_selectionne = request.args.get('filter_lot', '')
        
        # Configuration de la pagination native
        page = request.args.get('page', 1, type=int)
        per_page = 20 # Performance optimale assurée en base de données
        
        # Chargement ciblé sur la vraie chaîne textuelle présente en base de données (Exclut les stocks à 0 si désiré)
        produits_veto = Produit.query.filter(
            Produit.categorie == "Produits vétérinaires"
        ).order_by(Produit.designation.asc()).all()
        
        # 2. Cloisonnement multi-utilisateur étanche
        if est_admin:
            lots_disponibles = LotAvicole.query.all()
            query_base = Vaccination.query
        else:
            lots_disponibles = LotAvicole.query.filter_by(id_user=user_id_connecte).all()
            query_base = Vaccination.query.filter(Vaccination.id_user == user_id_connecte)
            
        # Filtrage chronologique côté base de données
        query_base = query_base.filter(
            db.extract('month', Vaccination.date_vaccination) == int(mois_selectionne),
            db.extract('year', Vaccination.date_vaccination) == int(annee_selectionnee)
        )
        if lot_selectionne:
            query_base = query_base.filter(Vaccination.id_lot == int(lot_selectionne))
            
        # Tri et pagination native au niveau du serveur SQL
        query_base = query_base.order_by(Vaccination.date_vaccination.desc())
        pagination = query_base.paginate(page=page, per_page=per_page, error_out=False)
        registres = pagination.items
        
        # Jointures dynamiques pour construire les attributs virtuels du tableau
        for r in registres:
            r.date_iso = r.date_vaccination.strftime('%Y-%m-%d') if r.date_vaccination else ''
            r.date_affichage = r.date_vaccination.strftime('%d/%m/%Y') if r.date_vaccination else ''
            
            if r.produit:
                r.nom_intrant = r.produit.designation
                r.unite_intrant = r.produit.unite or 'ut'
                des_lower = r.produit.designation.lower()
                if 'vaccin' in des_lower:
                    r.sous_categorie = "Vaccin"
                elif 'antibio' in des_lower:
                    r.sous_categorie = "Antibiotique"
                elif 'vitam' in des_lower:
                    r.sous_categorie = "Vitamine"
                else:
                    r.sous_categorie = "Consommable"
            else:
                r.nom_intrant = "Inconnu"
                r.unite_intrant = "ut"
                r.sous_categorie = "Inconnue"
                
        # Génération de l'historique des années pour le composant de filtrage
        annees_dispo = db.session.query(db.extract('year', Vaccination.date_vaccination).distinct()).all()
        liste_annees = [int(a[0]) for a in annees_dispo if a[0] is not None]
        if int(annee_selectionnee) not in liste_annees:
            liste_annees.append(int(annee_selectionnee))
            
        return render_template(
            'vaccination.html',
            registres=registres,
            pagination=pagination, # Transmission de la pagination au template HTML
            lots=lots_disponibles,
            produits=produits_veto,
            entreprise=infos_entreprise,
            liste_annees=sorted(liste_annees, reverse=True),
            mois_sel=mois_selectionne,
            annee_sel=annee_selectionnee,
            lot_sel=lot_selectionne,
            est_admin=est_admin # Assure le blocage strict du bouton imprimer côté HTML
        )
    except Exception as e:
        db.session.rollback()
        return f"<h3>❌ Erreur d'exécution dans liste_vaccinations :</h3> <p>{str(e)}</p>"


@app.route('/vaccinations/ajouter', methods=['POST'])
def ajouter_vaccination():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    est_admin = utilisateur_connecte.Fonction.lower() in ['administrateur', 'admin', 'gérant']
    
    id_vaccination_modif = request.form.get('id_vaccination_modif')
    id_lot = request.form.get('id_lot')
    date_vaccination_str = request.form.get('date_vaccination')
    id_produit = request.form.get('id_produit')
    quantite_utilisee = request.form.get('quantite_utilisee', 1)
    dose = request.form.get('dose', '').strip()
    
    if not all([id_lot, date_vaccination_str, id_produit]):
        flash("❌ Erreur : Veuillez renseigner tous les champs obligatoires (*).", "error")
        return redirect(url_for('liste_vaccinations'))
   
    try:
        id_lot_int = int(id_lot)
        id_prod_int = int(id_produit)
        qte_int = int(quantite_utilisee)
        
        # Cloisonnement : vérification des droits de l'ouvrier sur le lot
        if not est_admin:
            lot_attribue = LotAvicole.query.filter_by(id_lot=id_lot_int, id_user=user_id_connecte).first()
            if not lot_attribue:
                flash("❌ Enregistrement refusé : Vous n'êtes pas responsable de ce lot.", "error")
                return redirect(url_for('liste_vaccinations'))
                
        date_vaccination = datetime.strptime(date_vaccination_str, '%Y-%m-%d').date()
        lot = LotAvicole.query.get(id_lot_int)
        produit_veto = Produit.query.get(id_prod_int)
        
        # ==============================================================================
        # VERROUILLAGE ANTI-DOUBLON SANITAIRE (MÊME LOT + MÊME DATE + MÊME PRODUIT)
        # ==============================================================================
        critere_doublon = [
            Vaccination.id_lot == id_lot_int,
            Vaccination.date_vaccination == date_vaccination,
            Vaccination.id_produit == id_prod_int
        ]
        
        # Si on est en mode modification, on ignore la ligne actuelle pour la recherche de doublons
        if id_vaccination_modif and id_vaccination_modif.strip() != "":
            critere_doublon.append(Vaccination.id_vaccination != int(id_vaccination_modif))
            
        acte_existant = Vaccination.query.filter(and_(*critere_doublon)).first()
        if acte_existant:
            flash(f"❌ Erreur : Un enregistrement existe déjà pour le produit '{produit_veto.designation}' sur le lot {lot.code_lot} à la date du {date_vaccination.strftime('%d/%m/%Y')}.", "error")
            return redirect(url_for('liste_vaccinations'))
        # ==============================================================================

        # --- CAS 1 : MODE MODIFICATION SÉCURISÉ ---
        if id_vaccination_modif and id_vaccination_modif.strip() != "":
            fiche = Vaccination.query.get(int(id_vaccination_modif))
            if fiche:
                if not est_admin and fiche.id_user != user_id_connecte:
                    flash("❌ Action interdite.", "error")
                    return redirect(url_for('liste_vaccinations'))
                    
                fiche.id_lot = id_lot_int
                fiche.date_vaccination = date_vaccination
                fiche.id_produit = id_prod_int
                fiche.quantite_utilisee = qte_int
                fiche.dose = dose if dose else None
                flash("✔ Le rapport sanitaire a été rectifié avec succès !", "success")
                
        # Dans la section CAS 2 : MODE NOUVEL AJOUT
        else:
            produit_veto = Produit.query.get(id_prod_int)
    
    # Blocage strict si le stock est inférieur ou ÉGAL à 0, ou insuffisant
            if produit_veto and (produit_veto.stock <= 0 or produit_veto.stock < qte_int):
                flash(f"❌ Action impossible : Le produit '{produit_veto.designation}' est en rupture de stock ou insuffisant (Stock actuel : {produit_veto.stock}).", "error")
            return redirect(url_for('liste_vaccinations'))
            
            nouvelle_vaccination = Vaccination(
                id_lot=id_lot_int,
                date_vaccination=date_vaccination,
                id_produit=id_prod_int,
                quantite_utilisee=qte_int,
                dose=dose if dose else None,
                id_user=user_id_connecte
            )
            db.session.add(nouvelle_vaccination)
            flash("✔ Acte sanitaire enregistré ! Produit déduit de la pharmacie.", "success")
            
        db.session.commit()
        
        try:
            parties = date_vaccination_str.split('-')
            return redirect(url_for('liste_vaccinations') + f"?filter_lot={id_lot}&filter_mois={parties[1]}&filter_annee={parties[0]}")
        except Exception:
            return redirect(url_for('liste_vaccinations'))
            
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'écriture dans le registre sanitaire : {str(e)}", "error")
        return redirect(url_for('liste_vaccinations'))

#--------------------------------------------------------
# ROUTINE EMPLOYES COMPLÈTE & ALIGNÉE
# -------------------------------------------------------
@event.listens_for(Employe, 'before_insert')
def generer_matricule_automatique(mapper, connection, target):
    """
    Génère automatiquement un matricule unique incrémental au format ANNEE-PROMAS-000X
    Exemple : 2026-PROMAS-0001, 2026-PROMAS-0002...
    """
    annee_actuelle = datetime.now().year
    
    # 🔴 CORRECTION COMPTAGE GLOBAL : Récupère le nombre total de fiches pour l'incrémentation
    result = connection.execute(
        db.select(func.count(Employe.id_employe))
    ).scalar()
    
    prochain_index = (result or 0) + 1
    
    # Rendu définitif unique
    target.matricule = f"{annee_actuelle}-PROMAS-{prochain_index:04d}"

from flask import render_template, request, session, redirect, url_for, flash
from datetime import datetime
from sqlalchemy.orm import joinedload

from flask import render_template, request, session, redirect, url_for, flash
from datetime import datetime
from sqlalchemy.orm import joinedload
from sqlalchemy import asc, desc

@app.route('/employes')
def list_employes():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    
    try:
        user_id_connecte = session['user_id']
        utilisateur_connecte = Users.query.get(user_id_connecte)
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
        
        fonction_clean = utilisateur_connecte.Fonction.lower().strip()
        est_admin = fonction_clean in ['administrateur', 'admin', 'gérant', 'directeur']
        
        if not est_admin:
            flash("❌ Accès refusé : Cet espace de gestion comptable est réservé à la direction.", "error")
            return redirect(url_for('index')) 

        # 1. Gestion du Tri Dynamique
        tri_par = request.args.get('tri_par', 'id_employe')  # Tri par défaut
        ordre = request.args.get('ordre', 'desc')           # Ordre par défaut
        
        # Mapping des colonnes autorisées pour éviter les injections SQL
        colonnes_valides = {
            'matricule': Employe.matricule,
            'cin': Employe.cin,
            'nom': Employe.nom,
            'date_naissance': Employe.date_naissance,
            'lieu_naissance': Employe.lieu_naissance,
            'telephone': Employe.telephone,
            'adresse': Employe.adresse,
            'date_embauche': Employe.date_embauche,
            'id_employe': Employe.id_employe
        }
        
        critere_tri = colonnes_valides.get(tri_par, Employe.id_employe)
        application_tri = desc(critere_tri) if ordre == 'desc' else asc(critere_tri)

        # 2. Paramètres de pagination
        page = request.args.get('page', 1, type=int)
        par_page = 10
        
        entreprise = Configuration.query.first()
        datetime_actuelle = datetime.now()
        
        # 3. Requête SQL avec Jointure, Tri Dynamique et Pagination
        pagination = Employe.query.options(joinedload(Employe.user))\
            .order_by(application_tri)\
            .paginate(page=page, per_page=par_page, error_out=False)
            
        employes = pagination.items
        utilisateurs_disponibles = Users.query.order_by(Users.NomUtilisateur.asc()).all()
        
        return render_template(
            'employes.html', 
            employes=employes, 
            pagination=pagination,
            est_admin=est_admin, 
            utilisateurs_disponibles=utilisateurs_disponibles,
            entreprise=entreprise,
            datetime_actuelle=datetime_actuelle,
            tri_par=tri_par,  # Renvoyé au template pour marquer la colonne active
            ordre=ordre       # Renvoyé au template pour inverser au clic
        )
        
    except Exception as e:
        db.session.rollback()
        return f"<h3>❌ Erreur de chargement de la page :</h3> <p>{str(e)}</p>"

@app.route('/employes/ajouter', methods=['POST'])
def ajouter_employe():
    if not session.get('user_id'):
        flash("Vous devez être connecté pour effectuer cette action.", "error")
        return redirect(url_for('login'))
        
    # Récupération des données du formulaire
    cin = request.form.get('cin')
    prenom = request.form.get('prenom')
    nom = request.form.get('nom')
    date_naissance = request.form.get('date_naissance')
    lieu_naissance = request.form.get('lieu_naissance')
    telephone = request.form.get('telephone')
    adresse = request.form.get('adresse')
    
    # 1. Génération automatique du Matricule (Ex: EMP-2026-XXXX)
    # Vous pouvez adapter la logique de génération selon vos préférences
    prefixe = f"EMP-{datetime.now().year}-"
    dernier_emp = Employe.query.filter(Employe.matricule.like(f"{prefixe}%")).count()
    matricule = f"{prefixe}{dernier_emp + 1:04d}"
    
    # 2. Assignation automatique de l'administrateur connecté (Traçabilité)
    # session['user_id'] contient l'ID de l'admin actuel. Plusieurs employés auront cet ID.
    id_admin_connecte = session.get('user_id') 

    nouvel_employe = Employe(
        matricule=matricule,
        cin=cin,
        prenom=prenom,
        nom=nom,
        date_naissance=datetime.strptime(date_naissance, '%Y-%m-%d').date(),
        lieu_naissance=lieu_naissance,
        telephone=telephone,
        adresse=adresse,
        date_embauche=datetime.now().date(),
        id_user=id_admin_connecte # Liaison de traçabilité sécurisée
    )
    
    try:
        db.session.add(nouvel_employe)
        db.session.commit()
        flash(f"Employé créé avec succès ! Matricule généré : {matricule}", "success")
    except Exception as e:
        db.session.rollback()
        flash("Erreur lors de l'enregistrement. Vérifiez si le CIN ou le Matricule existe déjà.", "error")
        
    return redirect(url_for('list_employes')) # Nom de votre route de redirection

@app.route('/employes/modifier/<int:id_employe>', methods=['POST'])
def modifier_employe(id_employe):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    user_id_connecte = session['user_id']
    utilisateur_connecte = db.session.get(Users, user_id_connecte)
    if not utilisateur_connecte:
        flash("❌ Utilisateur introuvable.", "error")
        return redirect(url_for('connexion_get'))

    fonction_clean = utilisateur_connecte.Fonction.lower().strip()
    est_admin = fonction_clean in ['administrateur', 'admin', 'gérant', 'directeur']
    if not est_admin:
        flash("❌ Action interdite : Droits d'administration requis.", "error")
        return redirect(url_for('list_employes'))

    fiche = db.session.get(Employe, id_employe)
    if not fiche:
        flash("❌ Fiche employé introuvable.", "error")
        return redirect(url_for('list_employes'))

    cin = request.form.get('cin', '').strip()
    prenom = request.form.get('prenom', '').strip()
    nom = request.form.get('nom', '').strip()
    date_naissance_str = request.form.get('date_naissance')
    lieu_naissance = request.form.get('lieu_naissance', '').strip()
    telephone = request.form.get('telephone', '').strip()
    adresse = request.form.get('adresse', '').strip()
    id_user_lie = request.form.get('id_user')

    if not all([cin, prenom, nom, date_naissance_str, lieu_naissance]):
        flash("❌ Erreur : Veuillez renseigner tous les champs obligatoires (*).", "error")
        return redirect(url_for('list_employes'))

    try:
        if cin != fiche.cin:
            cin_existe = Employe.query.filter_by(cin=cin).first()
            if cin_existe:
                flash("❌ Erreur : Ce numéro de CIN est déjà attribué.", "error")
                return redirect(url_for('list_employes'))

        date_naissance = datetime.strptime(date_naissance_str, '%Y-%m-%d').date()
        id_user_int = int(id_user_lie) if id_user_lie and id_user_lie != "" else None
        
        if id_user_int and id_user_int != fiche.id_user:
            deja_lie = Employe.query.filter_by(id_user=id_user_int).first()
            if deja_lie:
                flash(f"⚠️ Attention : Ce compte utilisateur est déjà rattaché à {deja_lie.prenom} {deja_lie.nom}.", "error")
                return redirect(url_for('list_employes'))

        # Application stricte des modifications
        fiche.cin = cin
        fiche.prenom = prenom
        fiche.nom = nom
        fiche.date_naissance = date_naissance
        fiche.lieu_naissance = lieu_naissance
        fiche.telephone = telephone if telephone else None
        fiche.adresse = adresse if adresse else None
        fiche.id_user = id_user_int
        
        db.session.commit()
        flash(f"✔️ La fiche de l'employé {prenom} {nom} a été rectifiée avec succès !", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur lors de la mise à jour de la fiche : {str(e)}", "error")
        
    return redirect(url_for('list_employes'))


@app.route('/employes/exporter')
def exporter_employes_excel():
    # Sécurité : Vérification d'accès administrateur
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    utilisateur_connecte = Users.query.get(session['user_id'])
    if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur']:
        flash("❌ Action interdite : Droits d'administration requis.", "error")
        return redirect(url_for('index'))
    
    # Récupération de l'intégralité du personnel (sans pagination pour l'export complet)
    employes = Employe.query.options(joinedload(Employe.user)).order_by(Employe.id_employe.desc()).all()
    
    # Structuration des données pour Excel
    donnees = []
    for emp in employes:
        donnees.append({
            "Matricule": emp.matricule,
            "CIN": emp.cin,
            "Enregistré Par": f"@{emp.user.NomUtilisateur}" if emp.user else "Aucun",
            "Nom Complet": f"{emp.prenom} {emp.nom}",
            "Date de Naissance": emp.date_naissance.strftime('%d/%m/%Y') if emp.date_naissance else "Non renseignée",
            "Lieu de Naissance": emp.lieu_naissance or "Non spécifié",
            "Téléphone": emp.telephone or "Non spécifié",
            "Adresse": emp.adresse or "Non spécifiée",
            "Date d'Embauche": emp.date_embauche.strftime('%d/%m/%Y') if emp.date_embauche else "Non renseignée"
        })
    
    # Création du DataFrame et écriture en mémoire
    df = pd.DataFrame(donnees)
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Registre Personnel')
        
    output.seek(0)
    
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"Registre_Personnel_{datetime.now().strftime('%d_%m_%Y')}.xlsx"
    )
#--------------------------------------------------------
# ROUTINES SUIVI CONTRATRAT
# -------------------------------------------------------

@app.route('/suivicontrats')
def suivi_contrats():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    try:
        user_id_connecte = session['user_id']
        utilisateur_connecte = Users.query.get(user_id_connecte)
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))

        # 1. BARRIÈRE DE SÉCURITÉ : Accès réservé uniquement à la direction
        fonction_clean = utilisateur_connecte.Fonction.lower().strip()
        est_admin = fonction_clean in ['administrateur', 'admin', 'gérant', 'directeur']
        if not est_admin:
            flash("❌ Accès refusé : Cet espace de gestion comptable est réservé à la direction.", "error")
            return redirect(url_for('list_employes'))

        entreprise = Configuration.query.first()
        datetime_actuelle = datetime.now()

        # 2. CONFIGURATION DE LA PAGINATION NATIVE
        page = request.args.get('page', 1, type=int)
        par_page = 10  # Limite stricte à 10 contrats par page au niveau SQL

        # 3. EXTRACTION ULTRA-RAPIDE ET PAGINÉE DU JOURNAL DES CONTRATS
        pagination = Contrat.query.order_by(Contrat.date_debut.desc())\
            .paginate(page=page, per_page=par_page, error_out=False)
            
        tous_les_contrats = pagination.items
        id_employes_période = [c.id_employe for c in tous_les_contrats]
        liste_contrats_unifiee = []

        if id_employes_période:
            # Récupération groupée en 1 seule passe pour les éléments de la page actuelle (RAM 100% optimisée)
            catalogue_employes = {e.id_employe: e for e in
                Employe.query.filter(Employe.id_employe.in_(id_employes_période)).all()}
            
            toutes_affectations = {a.id_employe: a for a in
                AffectationPoste.query.options(joinedload(AffectationPoste.poste)).filter(AffectationPoste.id_employe.in_(id_employes_période)).all()}
            
            tous_les_salaires = {s.id_employe: s for s in
                Salaire.query.filter(Salaire.id_employe.in_(id_employes_période)).all()}

            # Assemblage en mémoire RAM sans requêtes SQL imbriquées
            for ctr in tous_les_contrats:
                emp = catalogue_employes.get(ctr.id_employe)
                if not emp:
                    continue
                aff = toutes_affectations.get(emp.id_employe)
                poste_libelle = aff.poste.libelle_poste if (aff and aff.poste) else "Ouvrier Avicole"
                
                sal = tous_les_salaires.get(emp.id_employe)
                mode_remun = sal.mode_renumeration if sal else "Mensuel"
                montant_forfait = sal.montant if sal else 0.0

                liste_contrats_unifiee.append({
                    'id_contrat': ctr.id_contrat,
                    'id_employe': emp.id_employe,
                    'matricule': emp.matricule,
                    'nom_complet': f"{emp.prenom} {emp.nom}",
                    'type_contrat': ctr.type_contrat,
                    'duree_contrat': ctr.duree_contrat,
                    'poste_occupe': poste_libelle,
                    'mode_renumeration': mode_remun,
                    'salaire_forfaitaire': montant_forfait,
                    'date_debut': ctr.date_debut
                })

        employes_dropdown = Employe.query.order_by(Employe.nom.asc()).all()
        
        return render_template(
            'suivicontrats.html', 
            contrats_affiches=liste_contrats_unifiee,
            pagination=pagination, # Transmission de l'objet de pagination au template
            employes=employes_dropdown, 
            est_admin=est_admin, 
            entreprise=entreprise, 
            datetime_actuelle=datetime_actuelle
        )
    except Exception as e:
        db.session.rollback()
        return f"<h3>❌ Erreur d'exécution de suivi_contrats :</h3> <p>{str(e)}</p>"


@app.route('/contrats/ajouter', methods=['POST'])
def ajouter_contract_affectation():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # SÉCURITÉ : Vérification des privilèges de la direction avant traitement
        user_id_connecte = session['user_id']
        utilisateur_connecte = Users.query.get(user_id_connecte)
        if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur']:
            flash("❌ Action interdite : Droits insuffisants.", "error")
            return redirect(url_for('suivi_contrats'))

        id_employe = request.form.get('id_employe')
        type_contrat = request.form.get('type_contrat')
        duree_contrat = request.form.get('duree_contrat', 0)
        mode_renumeration = request.form.get('mode_renumeration')
        montant_salaire = request.form.get('salaire_forfaitaire')
        date_debut_str = request.form.get('date_debut')
        fonction_saisie = request.form.get('fonction_interne', '').strip()

        if not all([id_employe, type_contrat, mode_renumeration, montant_salaire, date_debut_str, fonction_saisie]):
            flash("❌ Erreur : Veuillez renseigner tous les champs obligatoires (*).", "error")
            return redirect(url_for('suivi_contrats'))

        id_emp_int = int(id_employe)
        date_effet = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
        duree_int = int(duree_contrat) if type_contrat != 'CDI' else 0

        # 1. Gestion ou création automatique du Poste relationnel
        poste = Poste.query.filter(Poste.libelle_poste.ilike(fonction_saisie)).first()
        if not poste:
            poste = Poste(libelle_poste=fonction_saisie)
            db.session.add(poste)
            db.session.flush()

        # 2. Insertion synchrone du document Contrat
        nouveau_contrat = Contrat(
            type_contrat=type_contrat,
            date_debut=date_effet,
            duree_contrat=duree_int,
            id_employe=id_emp_int
        )
        db.session.add(nouveau_contrat)

        # 3. Insertion de l'AffectationPoste datée
        nouvelle_affectation = AffectationPoste(
            id_employe=id_emp_int,
            id_poste=poste.id_poste,
            date_affectation=date_effet
        )
        db.session.add(nouvelle_affectation)

        # 4. Insertion du Salaire Forfaitaire initial
        nouveau_salaire = Salaire(
            mode_renumeration=mode_renumeration,
            montant=float(montant_salaire),
            date_salaire=date_effet,
            id_employe=id_emp_int
        )
        db.session.add(nouveau_salaire)
        
        db.session.commit()
        flash("✔ Mutation contractuelle et historique de carrière mis à jour avec succès !", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur lors de l'enregistrement : {str(e)}", "error")
        
    return redirect(url_for('suivi_contrats'))

@app.route('/contrats/exporter')
def exporter_contrats_excel():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    utilisateur_connecte = Users.query.get(session['user_id'])
    if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur']:
        flash("❌ Action interdite : Droits d'administration requis.", "error")
        return redirect(url_for('suivi_contrats'))
    
    # Extraction complète en mémoire RAM pour l'export de l'historique
    tous_les_contrats = Contrat.query.order_by(Contrat.date_debut.desc()).all()
    id_employes_période = [c.id_employe for c in tous_les_contrats]
    
    donnees = []
    if id_employes_période:
        catalogue_employes = {e.id_employe: e for e in Employe.query.filter(Employe.id_employe.in_(id_employes_période)).all()}
        toutes_affectations = {a.id_employe: a for a in AffectationPoste.query.options(joinedload(AffectationPoste.poste)).filter(AffectationPoste.id_employe.in_(id_employes_période)).all()}
        tous_les_salaires = {s.id_employe: s for s in Salaire.query.filter(Salaire.id_employe.in_(id_employes_période)).all()}

        for ctr in tous_les_contrats:
            emp = catalogue_employes.get(ctr.id_employe)
            if not emp:
                continue
            aff = toutes_affectations.get(emp.id_employe)
            poste_libelle = aff.poste.libelle_poste if (aff and aff.poste) else "Ouvrier Avicole"
            sal = tous_les_salaires.get(emp.id_employe)
            mode_remun = sal.mode_renumeration if sal else "Mensuel"
            montant_forfait = sal.montant if sal else 0.0

            donnees.append({
                "Matricule": emp.matricule,
                "Employé": f"{emp.prenom} {emp.nom}",
                "Type Contrat": ctr.type_contrat,
                "Durée (Mois)": "Indéterminée" if ctr.type_contrat == 'CDI' else f"{ctr.duree_contrat} mois",
                "Poste Occupé": poste_libelle,
                "Type Rémunération": mode_remun,
                "Forfait Salarial (FCFA)": montant_forfait,
                "Date de Prise d'Effet": ctr.date_debut.strftime('%d/%m/%Y') if ctr.date_debut else ""
            })
            
    df = pd.DataFrame(donnees)
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Historique Contrats')
        
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"Historique_Contrats_{datetime.now().strftime('%d_%m_%Y')}.xlsx"
    )


@app.route('/contrats/modifier/', methods=['POST'])
@app.route('/contrats/modifier/<int:id_contrat>', methods=['POST'])
def modifier_contrat_affectation(id_contrat=None):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    try:
        # 1. SÉCURITÉ : Contrôle des accès de la direction
        id_admin_connecte = session['user_id']
        utilisateur_connecte = db.session.get(Users, id_admin_connecte)
        if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur']:
            flash("❌ Action interdite : Privilèges administratifs requis.", "error")
            return redirect(url_for('suivi_contrats'))

        # Secours ID formulaire si l'URL est vide
        if id_contrat is None:
            id_contrat = int(request.form.get('id_contrat') or request.form.get('id_contrat_modif'))

        ctr = db.session.get(Contrat, id_contrat)
        if not ctr:
            flash("❌ Fiche d'engagement introuvable.", "error")
            return redirect(url_for('suivi_contrats'))

        # 🎯 FIX TECHNIQUE CRUCIAL : Sauvegarder l'ancienne date d'effet AVANT de lire le formulaire
        ancienne_date_effet = ctr.date_debut
        id_du_salarie = ctr.id_employe

        # 2. Récupération des données transmises par le formulaire HTML
        type_contrat = request.form.get('type_contrat')
        duree_contrat = request.form.get('duree_contrat', 0)
        fonction_saisie = request.form.get('fonction_interne', '').strip()
        mode_renumeration = request.form.get('mode_renumeration')
        montant_salaire = request.form.get('salaire_forfaitaire')
        date_debut_str = request.form.get('date_debut')
        
        if not all([type_contrat, fonction_saisie, mode_renumeration, montant_salaire, date_debut_str]):
            flash("❌ Erreur : Veuillez remplir tous les champs obligatoires (*).", "error")
            return redirect(url_for('suivi_contrats'))

        date_effet_nouvelle = datetime.strptime(date_debut_str, '%Y-%m-%d').date()

        # 3. Extraction des liaisons d'origine basée sur l'ancienne date sauvegardée
        aff = AffectationPoste.query.filter_by(id_employe=id_du_salarie, date_affectation=ancienne_date_effet).first()
        sal = Salaire.query.filter_by(id_employe=id_du_salarie, date_salaire=ancienne_date_effet).first()
        
        # 4. Traitement automatique de l'intitulé du poste
        poste = Poste.query.filter(Poste.libelle_poste.ilike(fonction_saisie)).first()
        if not poste:
            poste = Poste(libelle_poste=fonction_saisie)
            db.session.add(poste)
            db.session.flush()

        # 5. Rectification et enregistrement synchrone dans les 3 tables métiers
        ctr.type_contrat = type_contrat
        ctr.date_debut = date_effet_nouvelle
        ctr.duree_contrat = int(duree_contrat) if type_contrat != 'CDI' else 0
        
        # Si l'affectation historique existe, on la met à jour, sinon on recrée une sécurité
        if aff:
            aff.id_poste = poste.id_poste
            aff.date_affectation = date_effet_nouvelle
        else:
            # Sécurité si aucune affectation n'était synchronisée à cette date exacte
            aff_secours = AffectationPoste.query.filter_by(id_employe=id_du_salarie).order_by(AffectationPoste.id_affectation.desc()).first()
            if aff_secours:
                aff_secours.id_poste = poste.id_poste
                aff_secours.date_affectation = date_effet_nouvelle

        if sal:
            sal.mode_renumeration = mode_renumeration
            sal.montant = float(montant_salaire)
            sal.date_salaire = date_effet_nouvelle
        else:
            # Sécurité si aucun salaire n'était synchronisé à cette date exacte
            sal_secours = Salaire.query.filter_by(id_employe=id_du_salarie).order_by(Salaire.id_salaire.desc()).first()
            if sal_secours:
                sal_secours.mode_renumeration = mode_renumeration
                sal_secours.montant = float(montant_salaire)
                sal_secours.date_salaire = date_effet_nouvelle
            
        db.session.commit()
        flash("✔ L'enregistrement contractuel et l'historique de carrière ont été rectifiés avec succès !", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur lors de la rectification : {str(e)}", "error")
        
    return redirect(url_for('suivi_contrats'))

 #--------------------------------------------------------
# ROUTINES SUIVI PAIE
# ------------------------------------------------------- 

@app.route('/paies', methods=['GET', 'POST'])
def gestion_paies():
    # =================================================================
    # VÉRIFICATION DE SÉCURITÉ ET ACCÈS UNIQUE À LA DIRECTION
    # =================================================================
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    try:
        user_id_connecte = session['user_id']
        utilisateur_connecte = Users.query.get(user_id_connecte)
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
        
        fonction_clean = utilisateur_connecte.Fonction.lower().strip()
        est_admin = fonction_clean in ['administrateur', 'admin', 'gérant', 'directeur']
        
        if not est_admin:
            flash("❌ Accès interdit : La gestion de la paie est réservée exclusivement à la direction.", "error")
            return redirect(url_for('list_employes'))

        # =================================================================
        # MÉTHODE POST : ENREGISTREMENT ET LIQUIDATION DE LA PAIE D'UN EMPLOYÉ
        # =================================================================
        if request.method == 'POST':
            id_employe_str = request.form.get('id_employe')
            periode_saisie = request.form.get('periode') 
            if not id_employe_str or not periode_saisie:
                flash("❌ Erreur : Employé ou période manquante.", "error")
                return redirect(url_for('gestion_paies', periode=periode_saisie))
            
            id_employe = int(id_employe_str)
            prime = float(request.form.get('prime') or 0.0)
            indemnite = float(request.form.get('indemnite') or 0.0)
            ipres = float(request.form.get('ipres') or 0.0)
            assurance = float(request.form.get('assurance') or 0.0)
            impot = float(request.form.get('impot') or 0.0)
            avance = float(request.form.get('avance') or 0.0)
            retenue = float(request.form.get('retenue') or 0.0)

            paie_existante = Paie.query.filter_by(id_employe=id_employe, periode=periode_saisie).first()
            if paie_existante:
                paie_existante.prime = prime
                paie_existante.indemnite = indemnite
                paie_existante.ipres = ipres
                paie_existante.assurance = assurance
                paie_existante.impot = impot
                paie_existante.avance = avance
                paie_existante.retenue = retenue
                flash("✔ Fiche de paie mise à jour avec succès !", "success")
            else:
                nouvelle_paie = Paie(
                    periode=periode_saisie,
                    date_paie=datetime.now().date(),
                    avance=avance,
                    retenue=retenue,
                    prime=prime,
                    indemnite=indemnite,
                    ipres=ipres,
                    assurance=assurance,
                    impot=impot,
                    id_employe=id_employe
                )
                db.session.add(nouvelle_paie)
                db.session.flush() 

                bloc_date = periode_saisie.replace("-", "")
                numero_bulletin = f"BL-{bloc_date}-{nouvelle_paie.id_paie}"
                nouveau_bulletin = BulletinSalaire(
                    numero_bulletin=numero_bulletin,
                    date_emission=datetime.now().date(),
                    id_paie=nouvelle_paie.id_paie
                )
                db.session.add(nouveau_bulletin)
                flash(f"✔ Paie liquidée avec succès ! Bulletin unique émis : {numero_bulletin}", "success")
            
            db.session.commit()
            return redirect(url_for('gestion_paies', periode=periode_saisie))

        # =================================================================
        # MÉTHODE GET : RENDU VISUEL & FILTRAGE ULTRA-RAPIDE PAGINÉ
        # =================================================================
        entreprise = Configuration.query.first()
        datetime_actuelle = datetime.now()
        periode_actuelle = request.args.get('periode', datetime_actuelle.strftime('%Y-%m'))
        
        # Gestion des paramètres de pagination
        page = request.args.get('page', 1, type=int)
        par_page = 10 

        # OPTIMISATION ANTI-N+1 ET PAGINATION : Seuls 10 employés sont extraits par page
        pagination = Employe.query.options(
            joinedload(Employe.salaires),
            joinedload(Employe.affectations).joinedload(AffectationPoste.poste)
        ).order_by(Employe.nom.asc()).paginate(page=page, per_page=par_page, error_out=False)
        
        employes_sur_la_page = pagination.items
        id_employes_visibles = [e.id_employe for e in employes_sur_la_page]

        # Extraction groupée limitée strictement aux employés de la page courante pour le mois actif
        paies_map = {}
        if id_employes_visibles:
            paies_période = Paie.query.filter(Paie.periode == periode_actuelle, Paie.id_employe.in_(id_employes_visibles)).all()
            paies_map = {p.id_employe: p for p in paies_période}

        liste_paies = []
        for emp in employes_sur_la_page:
            paie_existante = paies_map.get(emp.id_employe)
            salaire_actif = emp.salaires[-1].montant if emp.salaires else 0.0
            poste_actif = emp.affectations[-1].poste.libelle_poste if emp.affectations else "Ouvrier"

            prime_val = getattr(paie_existante, 'prime', 0.0) or 0.0
            indemnite_val = getattr(paie_existante, 'indemnite', 0.0) or 0.0
            ipres_val = getattr(paie_existante, 'ipres', 0.0) or 0.0
            assurance_val = getattr(paie_existante, 'assurance', 0.0) or 0.0
            impot_val = getattr(paie_existante, 'impot', 0.0) or 0.0
            avance_val = getattr(paie_existante, 'avance', 0.0) or 0.0
            retenue_val = getattr(paie_existante, 'retenue', 0.0) or 0.0

            liste_paies.append({
                'employe': emp,
                'id_employe': emp.id_employe,
                'matricule': emp.matricule,
                'nom_complet': f"{emp.prenom} {emp.nom}",
                'poste': poste_actif,
                'salaire_forfaitaire': salaire_actif,
                'paie': paie_existante,
                'prime': prime_val,
                'indemnite': indemnite_val,
                'ipres': ipres_val,
                'assurance': assurance_val,
                'impot': impot_val,
                'avance': avance_val,
                'retenue': retenue_val,
                'salaire_net': (salaire_actif + prime_val + indemnite_val) - (ipres_val + assurance_val + impot_val + avance_val + retenue_val)
            })

        return render_template(
            'paies.html', 
            liste_paies=liste_paies, 
            pagination=pagination,
            periode_actuelle=periode_actuelle,
            entreprise=entreprise,
            datetime_actuelle=datetime_actuelle
        )
    except Exception as e:
        db.session.rollback()
        return f"<h3>❌ Erreur de liquidation ou de calcul de la paie :</h3> <p>{str(e)}</p>"

@app.route('/paies/calculer', methods=['POST'])
def calculer_paie_employe():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    user_id_connecte = session['user_id']
    utilisateur_connecte = db.session.get(Users, user_id_connecte)
    if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur']:
        flash("❌ Action interdite.", "error")
        return redirect(url_for('list_employes'))
        
    id_employe = request.form.get('id_employe')
    periode = request.form.get('periode')
    
    if not id_employe or not periode:
        flash("❌ Erreur : Paramètres de paie invalides.", "error")
        return redirect(url_for('gestion_paies'))
        
    try:
        id_emp_int = int(id_employe)
        deja_paye = Paie.query.filter_by(id_employe=id_emp_int, periode=periode).first()
        if deja_paye:
            flash("❌ Saisie refusée : Un bulletin existe déjà.", "error")
            return redirect(url_for('gestion_paies', periode=periode))
            
        nouvelle_paie = Paie(
            periode=periode,
            date_paie=datetime.now().date(),
            id_employe=id_emp_int,
            avance=float(request.form.get('avance', 0.0) or 0.0),
            retenue=float(request.form.get('retenue', 0.0) or 0.0),
            prime=float(request.form.get('prime', 0.0) or 0.0),
            indemnite=float(request.form.get('indemnite', 0.0) or 0.0),
            ipres=float(request.form.get('ipres', 0.0) or 0.0),
            assurance=float(request.form.get('assurance', 0.0) or 0.0),
            impot=float(request.form.get('impot', 0.0) or 0.0)
        )
        db.session.add(nouvelle_paie)
        db.session.flush()
        
        annee_en_cours = datetime.now().year
        compteur = db.session.query(func.count(BulletinSalaire.id_bulletin)).scalar() or 0
        numero_bs = f"{annee_en_cours}-BS-{(compteur + 1):04d}"
        
        nouveau_bulletin = BulletinSalaire(
            numero_bulletin=numero_bs,
            date_emission=datetime.now().date(),
            id_paie=nouvelle_paie.id_paie
        )
        db.session.add(nouveau_bulletin)
        db.session.commit()
        flash(f"✔ Bulletin {numero_bs} généré avec succès !", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur lors du calcul financier : {str(e)}", "error")
        
    return redirect(url_for('gestion_paies', periode=periode))


@app.route('/paies/modifier/<int:id_paie>', methods=['POST'])
def modifier_paie(id_paie):
    # 1. Vérifier si l'administrateur est bien connecté en session
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    # 2. Récupérer l'enregistrement de paie unique dans la base de données
    paie = Paie.query.get_or_404(id_paie)
    
    # 3. Intercepter les nouveaux montants envoyés depuis les colonnes du tableau
    try:
        # Conversion et mise à jour de chaque champ (sécurisé avec repli à 0.0 si vide)
        paie.prime = float(request.form.get('prime', 0.0) or 0.0)
        paie.indemnite = float(request.form.get('indemnite', 0.0) or 0.0)
        
        # Les retenues maintenant séparées par colonnes
        paie.ipres = float(request.form.get('ipres', 0.0) or 0.0)
        paie.assurance = float(request.form.get('assurance', 0.0) or 0.0)
        paie.impot = float(request.form.get('impot', 0.0) or 0.0)
        
        # Les acomptes et retenues sur matériel
        paie.avance = float(request.form.get('avance', 0.0) or 0.0)
        paie.retenue = float(request.form.get('retenue', 0.0) or 0.0)
        
        # 4. Enregistrer les modifications de l'occurrence dans la base de données
        db.session.commit()
        flash("✔ Les montants du bulletin de salaire ont été mis à jour avec succès pour cet employé.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur lors de la modification des données comptables : {str(e)}", "error")
        
    # 5. Rediriger l'utilisateur vers la page des paies en conservant le mois actif
    return redirect(url_for('gestion_paies', periode=paie.periode))

@app.route('/paies/bulletin/<int:id_paie>')
def imprimer_bulletin(id_paie):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    paie = db.session.get(Paie, id_paie)
    if not paie:
        flash("❌ Fiche de paie introuvable.", "error")
        return redirect(url_for('gestion_paies'))
        
    # Récupération sécurisée de l'employé
    emp = db.session.get(Employe, paie.id_employe)
    entreprise = Configuration.query.first()
    date_du_jour_texte = datetime.now().strftime('%d/%m/%Y')
    
    # 1. Sécurisation du salaire forfaitaire de base
    salaire_brut = 0.0
    if emp.salaires:
        salaire_brut = float(emp.salaires[-1].montant)
        
    # 2. Sécurisation de la qualification professionnelle
    poste_libelle = "Ouvrier Avicole"
    if emp.affectations and emp.affectations[-1].poste:
        poste_libelle = emp.affectations[-1].poste.libelle_poste
        
    # 3. Extraction et nettoyage individuel des nouvelles colonnes comptables
    prime = float(getattr(paie, 'prime', 0.0) or 0.0)
    indemnite = float(getattr(paie, 'indemnite', 0.0) or 0.0)
    ipres = float(getattr(paie, 'ipres', 0.0) or 0.0)
    assurance = float(getattr(paie, 'assurance', 0.0) or 0.0)
    impot = float(getattr(paie, 'impot', 0.0) or 0.0)
    avance = float(getattr(paie, 'avance', 0.0) or 0.0)
    retenue = float(getattr(paie, 'retenue', 0.0) or 0.0)
    
    # 4. Modèle de calcul analytique du Net à Payer (Modèle Sénégalais)
    total_gains = salaire_brut + prime + indemnite
    total_retenues_fiscales = ipres + assurance + impot + retenue
    salaire_net = total_gains - avance - total_retenues_fiscales
    
    # 5. Sécurisation textuelle des dates
    date_paie_texte = paie.date_paie.strftime('%d/%m/%Y') if paie.date_paie else date_du_jour_texte
    date_embauche_texte = emp.date_embauche.strftime('%d/%m/%Y') if emp.date_embauche else 'Non spécifiée'
    type_contrat = getattr(emp, 'type_contrat', 'C.D.D')
    mode_paiement = getattr(emp, 'mode_paiement', 'Espèces')
    
    return render_template('bulletin_format.html', 
                           paie=paie, 
                           emp=emp, 
                           poste=poste_libelle,
                           type_contrat=type_contrat,
                           mode_paiement=mode_paiement,
                           salaire_brut=salaire_brut,
                           prime=prime,
                           indemnite=indemnite,
                           total_gains=total_gains,
                           ipres=ipres,
                           assurance=assurance,
                           impot=impot,
                           autres_retenues=retenue,
                           total_retenues_fiscales=total_retenues_fiscales,
                           total_avances=avance,
                           salaire_net=salaire_net,
                           entreprise=entreprise,
                           date_paie_texte=date_paie_texte,
                           date_embauche_texte=date_embauche_texte,
                           date_emission_bulletin=date_du_jour_texte,
                           datetime_actuelle=datetime.now())

@app.route('/paies/bulletins/tout/<path:periode>')
def imprimer_tous_bulletins(periode):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    # 1. Récupérer toutes les paies validées pour ce mois
    paies_du_mois = Paie.query.filter_by(periode=periode).all()
    
    if not paies_du_mois:
        flash(f"❌ Aucun bulletin de salaire disponible pour la période {periode}.", "error")
        return redirect(url_for('gestion_paies', periode=periode))
        
    entreprise = Configuration.query.first()
    date_du_jour_texte = datetime.now().strftime('%d/%m/%Y')
    
    liste_bulletins_calcules = []
    
    for paie in paies_du_mois:
        emp = db.session.get(Employe, paie.id_employe)
        if not emp:
            continue
            
        salaire_brut = 0.0
        if emp.salaires:
            salaire_brut = float(emp.salaires[-1].montant)
            
        poste_libelle = "Ouvrier Avicole"
        if emp.affectations and emp.affectations[-1].poste:
            poste_libelle = emp.affectations[-1].poste.libelle_poste
            
        # Extraction et nettoyage individuel des nouvelles colonnes comptables pour le traitement groupé
        prime = float(getattr(paie, 'prime', 0.0) or 0.0)
        indemnite = float(getattr(paie, 'indemnite', 0.0) or 0.0)
        ipres = float(getattr(paie, 'ipres', 0.0) or 0.0)
        assurance = float(getattr(paie, 'assurance', 0.0) or 0.0)
        impot = float(getattr(paie, 'impot', 0.0) or 0.0)
        avance = float(getattr(paie, 'avance', 0.0) or 0.0)
        retenue = float(getattr(paie, 'retenue', 0.0) or 0.0)
        
        # Application des équations comptables réglementaires
        total_gains = salaire_brut + prime + indemnite
        total_retenues_fiscales = ipres + assurance + impot + retenue
        salaire_net = total_gains - avance - total_retenues_fiscales
        
        # Sécurisation de la date de la paie en format texte
        date_paie_texte = paie.date_paie.strftime('%d/%m/%Y') if paie.date_paie else date_du_jour_texte
        
        # Sécurisation de la date d'embauche en format texte
        date_embauche_texte = emp.date_embauche.strftime('%d/%m/%Y') if emp.date_embauche else 'Non spécifiée'
        type_contrat = getattr(emp, 'type_contrat', 'C.D.D')
        mode_paiement = getattr(emp, 'mode_paiement', 'Espèces')
        
        liste_bulletins_calcules.append({
            'paie': paie,
            'emp': emp,
            'poste': poste_libelle,
            'type_contrat': type_contrat,
            'mode_paiement': mode_paiement,
            'salaire_brut': salaire_brut,
            'prime': prime,
            'indemnite': indemnite,
            'total_gains': total_gains,
            'ipres': ipres,
            'assurance': assurance,
            'impot': impot,
            'autres_retenues': retenue,
            'total_retenues_fiscales': total_retenues_fiscales,
            'total_avances': avance,
            'salaire_net': salaire_net,
            'date_paie_texte': date_paie_texte,
            'date_embauche_texte': date_embauche_texte
        })
        
    return render_template('bulletins_tout_format.html', 
                           liste_bulletins=liste_bulletins_calcules,
                           entreprise=entreprise,
                           periode_commune=periode,
                           date_emission_bulletin=date_du_jour_texte)

@app.route('/paies/exporter')
def exporter_paies_excel():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    utilisateur_connecte = Users.query.get(session['user_id'])
    if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur']:
        flash("❌ Action interdite : Droits d'administration requis.", "error")
        return redirect(url_for('gestion_paies'))
        
    periode_cible = request.args.get('periode', datetime.now().strftime('%Y-%m'))
    
    # Récupération globale de tous les employés et des paies associées à cette période précise
    employes = Employe.query.options(
        joinedload(Employe.salaires),
        joinedload(Employe.affectations).joinedload(AffectationPoste.poste)
    ).order_by(Employe.nom.asc()).all()
    
    paies_période = Paie.query.filter_by(periode=periode_cible).all()
    paies_map = {p.id_employe: p for p in paies_période}
    
    donnees = []
    for emp in employes:
        paie = paies_map.get(emp.id_employe)
        salaire_actif = emp.salaires[-1].montant if emp.salaires else 0.0
        poste_actif = emp.affectations[-1].poste.libelle_poste if emp.affectations else "Ouvrier"
        
        prime_val = getattr(paie, 'prime', 0.0) or 0.0
        indemnite_val = getattr(paie, 'indemnite', 0.0) or 0.0
        ipres_val = getattr(paie, 'ipres', 0.0) or 0.0
        assurance_val = getattr(paie, 'assurance', 0.0) or 0.0
        impot_val = getattr(paie, 'impot', 0.0) or 0.0
        avance_val = getattr(paie, 'avance', 0.0) or 0.0
        retenue_val = getattr(paie, 'retenue', 0.0) or 0.0
        
        salaire_net = (salaire_actif + prime_val + indemnite_val) - (ipres_val + assurance_val + impot_val + avance_val + retenue_val)
        statut = "Validé / Liquidé" if paie else "En attente de saisie"
        
        donnees.append({
            "Matricule": emp.matricule,
            "Employé": f"{emp.prenom} {emp.nom}",
            "Poste": poste_actif,
            "Salaire de Base (FCFA)": salaire_actif,
            "Primes (FCFA)": prime_val,
            "Indemnités (FCFA)": indemnite_val,
            "IPRES (-)": ipres_val,
            "IPM (-)": assurance_val,
            "Impôt IR (-)": impot_val,
            "Acomptes (-)": avance_val,
            "Retenues (-)": retenue_val,
            "Salaire Net (FCFA)": salaire_net,
            "État Comptable": statut
        })
        
    df = pd.DataFrame(donnees)
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=f'Paies {periode_cible}')
        
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"Etat_Salaires_{periode_cible}.xlsx"
    )

# =======================================================================
# MODULE : ENCAISSEMENT & RÈGLEMENTS DES ACHATS (PAIEMENT ACHAT)
# =======================================================================

@app.route('/paiements_achats', methods=['GET', 'POST'])
def gestion_paiements_achats():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    try:
        # 1. AUTHENTIFICATION & ROLES
        utilisateur_connecte = Users.query.get(session['user_id'])
        if not utilisateur_connecte:
            session.clear()
            return redirect(url_for('connexion_get'))
            
        fonction_user = utilisateur_connecte.Fonction.lower().strip()
        roles_superieurs = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
        roles_autorises = roles_superieurs + ['caissier', 'caissière']
        
        if fonction_user not in roles_autorises:
            flash("Accès refusé : Privilèges insuffisants.", "error")
            return redirect(url_for('index'))
            
        est_admin_ou_comptable = fonction_user in roles_superieurs

        # -----------------------------------------------------------------
        # TRAITEMENT DU FORMULAIRE : ENREGISTREMENT OU MODIFICATION (POST)
        # -----------------------------------------------------------------
        if request.method == 'POST':
            id_achat_str = request.form.get('id_achat')
            montant_paye_str = request.form.get('montant_paye')
            mode_paiement = request.form.get('mode_paiement')
            reference = request.form.get('reference', '').strip()
            date_str = request.form.get('date_paiement')
            id_paiement_modif = request.form.get('modifier_id_paiement')

            if not all([id_achat_str, montant_paye_str, mode_paiement, date_str]):
                if id_paiement_modif: return "Champs obligatoires manquants", 400
                flash("Veuillez remplir tous les champs obligatoires (*).", "error")
                return redirect(url_for('gestion_paiements_achats'))

            id_achat = int(id_achat_str)
            montant_paye = float(montant_paye_str)
            date_paiement = datetime.strptime(date_str, '%Y-%m-%d').date()

            # Utilisation explicite du modèle Achat
            achat_cible = Achat.query.get(id_achat)
            if not achat_cible:
                if id_paiement_modif: return "Le bon d'achat spécifié est introuvable.", 404
                flash("Le bon d'achat spécifié est introuvable.", "error")
                return redirect(url_for('gestion_paiements_achats'))

            # CLOISONNEMENT DE SÉCURITÉ basé sur le id_user de la table achat
            if not est_admin_ou_comptable and achat_cible.id_user != session['user_id']:
                if id_paiement_modif: return "Action interdite : Cet achat ne vous appartient pas.", 403
                flash("Action interdite : Vous ne pouvez pas régler un achat créé par un autre opérateur.", "error")
                return redirect(url_for('gestion_paiements_achats'))

            # Calculs sécurisés anti-surpaiement
            total_facture_achat = db.session.query(
                func.sum(achat_produit.c.quantite * achat_produit.c.prix_unitaire)
            ).filter(achat_produit.c.id_achat == id_achat).scalar() or 0.0

            total_deja_regle_query = db.session.query(func.sum(PaiementAchat.montant_paye)).filter(
                PaiementAchat.id_achat == id_achat
            )
            if id_paiement_modif:
                total_deja_regle_query = total_deja_regle_query.filter(PaiementAchat.id_paiement_achat != int(id_paiement_modif))
            
            total_deja_regle = total_deja_regle_query.scalar() or 0.0
            reste_a_payer = total_facture_achat - total_deja_regle

            if montant_paye > (reste_a_payer + 0.1):
                msg = f"Saisie refusée : Le versement ({int(montant_paye):,} FCFA) dépasse le reste dû ({int(reste_a_payer):,} FCFA)."
                if id_paiement_modif: return msg, 400
                flash(msg, "error")
                return redirect(url_for('gestion_paiements_achats'))

            if id_paiement_modif:
                paiement_existant = PaiementAchat.query.get(int(id_paiement_modif))
                if not paiement_existant: return "Paiement introuvable", 404
                paiement_existant.montant_paye = montant_paye
                paiement_existant.mode_paiement = mode_paiement
                paiement_existant.reference = reference if reference else None
                paiement_existant.date_paiement = date_paiement
                db.session.commit()
                return "OK", 200
            else:
                nouveau_reglement = PaiementAchat(
                    id_achat=id_achat, montant_paye=montant_paye, mode_paiement=mode_paiement,
                    reference=reference if reference else None, date_paiement=date_paiement, id_user=session['user_id']
                )
                db.session.add(nouveau_reglement)
                db.session.commit()
                flash(f"✔ Règlement de {int(montant_paye):,} FCFA validé sur l'achat N° {id_achat} !", "success")
                return redirect(url_for('gestion_paiements_achats'))

        # -----------------------------------------------------------------
        # RECUPÉRATION DES DONNÉES ET AFFICHAGE COMPTABLE (GET)
        # -----------------------------------------------------------------
        page = request.args.get('page', 1, type=int)
        par_page = 40
        maintenant = datetime.now()
        mois_sel = request.args.get('filter_mois', maintenant.strftime('%m'))
        annee_sel = request.args.get('filter_annee', maintenant.strftime('%Y'))

        query_paiements = PaiementAchat.query.options(
            joinedload(PaiementAchat.achat).joinedload(Achat.fournisseur),
            joinedload(PaiementAchat.user)
        ).filter(
            extract('month', PaiementAchat.date_paiement) == int(mois_sel),
            extract('year', PaiementAchat.date_paiement) == int(annee_sel)
        )

        if not est_admin_ou_comptable:
            query_paiements = query_paiements.filter(PaiementAchat.id_user == session['user_id'])

        pagination = query_paiements.order_by(PaiementAchat.date_paiement.desc(), PaiementAchat.id_paiement_achat.desc()).paginate(
            page=page, per_page=par_page, error_out=False
        )

        # Extraction et filtrage dynamique du menu déroulant (Purger si réglé)
        if est_admin_ou_comptable:
            achats_bruts = Achat.query.order_by(Achat.date_achat.desc()).limit(100).all()
        else:
            # Sécurisé : Utilise id_user validé par votre modèle Achat
            achats_bruts = Achat.query.filter_by(id_user=session['user_id']).order_by(Achat.date_achat.desc()).all()

        achats_dispo = []
        for ach in achats_bruts:
            total_facture = db.session.query(func.sum(achat_produit.c.quantite * achat_produit.c.prix_unitaire)).filter(achat_produit.c.id_achat == ach.id_achat).scalar() or 0.0
            total_regle = db.session.query(func.sum(PaiementAchat.montant_paye)).filter(PaiementAchat.id_achat == ach.id_achat).scalar() or 0.0
            reste = total_facture - total_regle
            if reste > 0:
                ach.reste_a_payer = reste
                achats_dispo.append(ach)

        # KPI
        sum_query = db.session.query(func.sum(PaiementAchat.montant_paye)).filter(
            extract('month', PaiementAchat.date_paiement) == int(mois_sel), extract('year', PaiementAchat.date_paiement) == int(annee_sel)
        )
        if not est_admin_ou_comptable:
            sum_query = sum_query.filter(PaiementAchat.id_user == session['user_id'])
        
        total_decaisse_val = sum_query.scalar()
        total_decaisse_periode = float(total_decaisse_val) if total_decaisse_val is not None else 0.0

        annees_rows = db.session.query(extract('year', PaiementAchat.date_paiement).distinct()).all()
        liste_annees = [int(r[0]) for r in annees_rows if r[0] is not None]
        if int(annee_sel) not in liste_annees: liste_annees.append(int(annee_sel))

        entreprise_config = Configuration.query.first()

        return render_template(
            'paiement_achat.html', paiements=pagination.items, pagination=pagination, achats=achats_dispo,
            total_decaisse=total_decaisse_periode, mois_sel=mois_sel, annee_sel=annee_sel,
            liste_annees=sorted(liste_annees, reverse=True), entreprise=entreprise_config, est_admin=est_admin_ou_comptable
        )

    except Exception as e:
        db.session.rollback()
        flash(f"Erreur d'accès au module : {str(e)}", "error")
        return redirect(url_for('index'))

# ==============================================================================
# ROUTINES APPLICATIVES : GESTION DES INVESTISSEMENTS (ADMINS UNIQUEMENT)
# ==============================================================================

@app.route('/investissements', methods=['GET'])
def liste_investissements():
    # 1. Vérification de la session active
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
    
    # 2. Identification de l'opérateur connecté et contrôle d'accès strict
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte:
        return redirect(url_for('connexion_get'))
        
    # Normalisation et vérification des rôles d'administration
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    
    est_admin = fonction_user in roles_admin
    
    # Sécurité absolue : Seuls les administrateurs accèdent à cette ressource
    if not est_admin:
        flash("❌ Accès interdit : Cette interface est réservée exclusivement aux administrateurs.", "error")
        return redirect(url_for('index')) # Redirection vers le tableau de bord général

    # 3. Récupération des informations de l'entreprise
    infos_entreprise = Configuration.query.first()

    # 4. Capture des filtres et paramètres de pagination de l'URL
    categorie_selectionnee = request.args.get('categorie', '')
    page = request.args.get('page', 1, type=int)
    per_page = 15 # Taille de lot pour un rendu de page instantané et ultra-rapide

    # Base de la requête sur le modèle Investissement
    query_base = Investissement.query

    # Application des filtres de recherche multicritères
    if categorie_selectionnee and categorie_selectionnee.strip() != "":
        query_base = query_base.filter(Investissement.categorie == categorie_selectionnee.strip())

    # Tri par date d'acquisition décroissante (les plus récents en premier)
    query_base = query_base.order_by(Investissement.date_acquisition.desc())
    
    # 5. Extraction paginée au niveau SQL (Évite le chargement massif en mémoire)
    pagination = query_base.paginate(page=page, per_page=per_page, error_out=False)
    liste_investissements = pagination.items

    # 6. Calcul des indicateurs financiers virtuels pour chaque ligne
    for inv in liste_investissements:
        inv.date_affichage = inv.date_acquisition.strftime('%d/%m/%Y') if inv.date_acquisition else ''
        inv.date_iso = inv.date_acquisition.strftime('%Y-%m-%d') if inv.date_acquisition else ''
        
        # Somme cumulée des paiements effectués pour cet investissement
        total_paye = db.session.query(func.sum(PaiementInvestissement.montant_paye)).filter(
            PaiementInvestissement.id_investissement == inv.id_investissement
        ).scalar() or 0.0
        
        inv.total_paye = total_paye
        inv.reste_a_payer = max(0.0, inv.montant - total_paye)

    # Récupération de la liste des catégories uniques pour le filtre déroulant
    categories_disponibles = db.session.query(Investissement.categorie.distinct()).all()
    liste_categories = [c[0] for c in categories_disponibles if c[0]]

    # À insérer dans la fonction liste_investissements() juste avant le return render_template
    liste_fournisseurs_bdd = Fournisseur.query.order_by(Fournisseur.nom.asc()).all()

    return render_template(
    'suiviinvestissement.html',
        investissements=liste_investissements,
        pagination=pagination,
        categories=liste_categories,
        categorie_active=str(categorie_selectionnee),
        fournisseurs=liste_fournisseurs_bdd,  # <--- Ajout de la liste des fournisseurs issus de la BDD
        entreprise=infos_entreprise,
        est_admin=est_admin
    )

@app.route('/investissements/ajouter', methods=['POST'])
def ajouter_investissement():
    # 1. Vérification de la session active
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    # 2. Contrôle d'accès strict (Admins uniquement)
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte:
        return redirect(url_for('connexion_get'))
        
    fonction_user = utilisateur_connecte.Fonction.lower().strip()
    roles_admin = ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']
    
    if fonction_user not in roles_admin:
        flash("❌ Action interdite : Seuls les administrateurs peuvent enregistrer un investissement.", "error")
        return redirect(url_for('liste_investissements'))

    # 3. Récupération et conversion des données du formulaire
    designation = request.form.get('designation', '').strip()
    categorie = request.form.get('categorie', '').strip()
    date_acq_str = request.form.get('date_acquisition')
    quantite = int(request.form.get('quantite') or 1)
    montant = float(request.form.get('montant') or 0.0)
    duree_amortissement = int(request.form.get('duree_amortissement') or 0)
    id_fournisseur = request.form.get('id_fournisseur')

    # Validation des champs requis
    if not all([designation, categorie, date_acq_str, id_fournisseur]) or montant <= 0 or duree_amortissement <= 0:
        flash("❌ Erreur : Veuillez remplir correctement tous les champs obligatoires (*).", "error")
        return redirect(url_for('liste_investissements'))

    try:
        date_acquisition = datetime.strptime(date_acq_str, '%Y-%m-%d').date()
        annee_demarrage = date_acquisition.year
        
        # 4. Création de l'entité Investissement
        nouvel_investissement = Investissement(
            designation=designation,
            categorie=categorie,
            date_acquisition=date_acquisition,
            quantite=quantite,
            montant=montant,
            duree_amortissement=duree_amortissement,
            id_fournisseur=int(id_fournisseur),
            id_user=user_id_connecte
        )
        db.session.add(nouvel_investissement)
        db.session.flush() # Permet d'obtenir l'id_investissement avant le commit pour la clé étrangère

        # 5. CONTRÔLE ET GÉNÉRATION AUTOMATIQUE DU PLAN D'AMORTISSEMENT
        # Calcul de l'annuité linéaire de base (Montant total / Nombre d'années)
        annuite_standard = round(montant / duree_amortissement, 2)
        
        for i in range(duree_amortissement):
            annee_calcul = annee_demarrage + i
            
            # Création de la ligne d'amortissement liée
            ligne_amortissement = Amortissement(
                annee=annee_calcul,
                montant_amortissement=annuite_standard,
                id_investissement=nouvel_investissement.id_investissement
            )
            db.session.add(ligne_amortissement)

        # Validation de l'ensemble de la transaction
        db.session.commit()
        flash(f"✔ L'investissement '{designation}' et son plan d'amortissement sur {duree_amortissement} ans ont été générés avec succès !", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur lors de l'enregistrement de l'investissement : {str(e)}", "error")
        
    return redirect(url_for('liste_investissements'))

@app.route('/investissements/<int:id_inv>/amortissements', methods=['GET'])
def obtenir_amortissements_json(id_inv):
    if 'user_id' not in session:
        return jsonify([]), 401
        
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']:
        return jsonify([]), 403

    liste_amortissements = Amortissement.query.filter_by(id_investissement=id_inv).order_by(Amortissement.annee.asc()).all()
    
    resultat = []
    for am in liste_amortissements:
        # Sécurité : Détection dynamique de l'attribut de montant pour éviter les crashs
        valeur_montant = 0.0
        if hasattr(am, 'montant_amortissement'):
            valeur_montant = am.montant_amortissement
        elif hasattr(am, 'montant'):
            valeur_montant = am.montant
            
        resultat.append({
            'annee': am.annee,
            'montant': valeur_montant
        })
        
    return jsonify(resultat)
@app.route('/investissements/modifier/<int:id_inv>', methods=['POST'])
def modifier_investissement(id_inv):
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']:
        flash("❌ Action refusée : Droits insuffisants.", "error")
        return redirect(url_for('liste_investissements'))
        
    fiche_invest = Investissement.query.get_or_404(id_inv)
    
    try:
        # Capture des données rectifiées
        fiche_invest.designation = request.form.get('designation', '').strip()
        fiche_invest.categorie = request.form.get('categorie', '').strip()
        fiche_invest.quantite = int(request.form.get('quantite') or 1)
        fiche_invest.id_fournisseur = int(request.form.get('id_fournisseur'))
        
        date_acq_str = request.form.get('date_acquisition')
        fiche_invest.date_acquisition = datetime.strptime(date_acq_str, '%Y-%m-%d').date()
        
        nouveau_montant = float(request.form.get('montant') or 0.0)
        nouvelle_duree = int(request.form.get('duree_amortissement') or 0)
        
        # Vérification si le montant ou la durée a changé pour recalculer le plan comptable
        if fiche_invest.montant != nouveau_montant or fiche_invest.duree_amortissement != nouvelle_duree:
            fiche_invest.montant = nouveau_montant
            fiche_invest.duree_amortissement = nouvelle_duree
            
            # Suppression sécurisée de l'ancien échéancier d'amortissements (delete-orphan automatique)
            Amortissement.query.filter_by(id_investissement=id_inv).delete()
            
            # Régénération instantanée du plan d'annuités linéaires réajusté
            annuite_calculee = round(nouveau_montant / nouvelle_duree, 2)
            annee_depart = fiche_invest.date_acquisition.year
            
            for i in range(nouvelle_duree):
                nouvelle_ligne = Amortissement(
                    annee=annee_depart + i,
                    montant_amortissement=annuite_calculee,
                    id_investissement=id_inv
                )
                db.session.add(nouvelle_ligne)
                
        db.session.commit()
        flash(f"✔ L'investissement '{fiche_invest.designation}' et son plan de dotations ont été mis à jour !", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur lors de la mise à jour comptable : {str(e)}", "error")
        
    return redirect(url_for('liste_investissements'))

@app.route('/investissements/payer', methods=['POST'])
def enregistrer_paiement_investissement():
    if 'user_id' not in session:
        return redirect(url_for('connexion_get'))
        
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']:
        flash("❌ Action refusée : Droits insuffisants pour émettre un règlement.", "error")
        return redirect(url_for('liste_investissements'))

    id_inv = request.form.get('id_investissement_paiement')
    montant_verse = float(request.form.get('montant_paye') or 0.0)
    date_paiement_str = request.form.get('date_paiement')
    mode_reglement = request.form.get('mode_paiement')
    reference = request.form.get('reference', '').strip()

    if not all([id_inv, date_paiement_str]) or montant_verse <= 0:
        flash("❌ Erreur : Paramètres de règlement invalides.", "error")
        return redirect(url_for('liste_investissements'))

    try:
        inv = Investissement.query.get_or_404(int(id_inv))
        
        # Calcul du reste à payer à cet instant précis
        total_deja_paye = db.session.query(func.sum(PaiementInvestissement.montant_paye)).filter(
            PaiementInvestissement.id_investissement == inv.id_investissement
        ).scalar() or 0.0
        reste_reel = inv.montant - total_deja_paye

        # Garde-fou : Interdiction de sur-payer l'actif
        if montant_verse > reste_reel:
            flash(f"❌ Refusé : Le montant versé ({montant_verse:,.2f} F CFA) excède le reste à payer actuel ({reste_reel:,.2f} F CFA).", "error")
            return redirect(url_for('liste_investissements'))

        # Création du ticket de paiement
        nouveau_paiement = PaiementInvestissement(
            date_paiement=datetime.strptime(date_paiement_str, '%Y-%m-%d').date(),
            montant_paye=montant_verse,
            mode_paiement=mode_reglement,
            reference=reference if reference else None,
            id_investissement=inv.id_investissement,
            id_user=user_id_connecte
        )
        db.session.add(nouveau_paiement)
        db.session.commit()
        
        flash(f"✔ Règlement de {montant_verse:,.2f} F CFA imputé avec succès sur l'investissement '{inv.designation}' !", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Erreur lors de l'écriture comptable du paiement : {str(e)}", "error")

    return redirect(url_for('liste_investissements'))

@app.route('/investissements/<int:id_inv>/paiements', methods=['GET'])
def obtenir_paiements_json(id_inv):
    if 'user_id' not in session:
        return jsonify([]), 401
        
    user_id_connecte = session['user_id']
    utilisateur_connecte = Users.query.get(user_id_connecte)
    if not utilisateur_connecte or utilisateur_connecte.Fonction.lower().strip() not in ['administrateur', 'admin', 'gérant', 'directeur', 'comptable']:
        return jsonify([]), 403

    try:
        historique = PaiementInvestissement.query.filter_by(id_investissement=id_inv).order_by(PaiementInvestissement.date_paiement.desc()).all()
        
        resultat = []
        for p in historique:
            # 1. Extraction de l'utilisateur avec tolérance sur la clé primaire (id_user ou id)
            id_cherche = getattr(p, 'id_user', None) or getattr(p, 'id', None)
            
            operateur = None
            if id_cherche:
                operateur = Users.query.get(id_cherche)
            
            # 2. Extraction du nom avec détection intelligente de l'attribut
            nom_operateur = "Inconnu"
            if operateur:
                if hasattr(operateur, 'Nom') and operateur.Nom:
                    nom_operateur = operateur.Nom
                elif hasattr(operateur, 'nom') and operateur.nom:
                    nom_operateur = operateur.nom
                elif hasattr(operateur, 'prenom') and hasattr(operateur, 'nom'):
                    nom_operateur = f"{operateur.prenom} {operateur.nom}".strip()
                elif hasattr(operateur, 'username') and operateur.username:
                    nom_operateur = operateur.username

            resultat.append({
                'date': p.date_paiement.strftime('%d/%m/%Y'),
                'mode': p.mode_paiement or 'Non spécifié',
                'reference': p.reference or '-',
                'operateur': nom_operateur,
                'montant': p.montant_paye
            })
            
        return jsonify(resultat)

    except Exception as e:
        print(f"⚠️ Erreur masquée dans obtenir_paiements_json : {str(e)}")
        return jsonify([])


#--------------------------------------------------------
# APPLICATION SECURE INITIALIZATION & RUN
# -------------------------------------------------------
if __name__ == "__main__":
    with app.app_context():
        # Création initiale des tables dans Neon si elles n'existent pas.
        # NE PAS utiliser db.drop_all() en production
        db.create_all()

    # Compatible avec Render et avec l'exécution locale.
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port)

