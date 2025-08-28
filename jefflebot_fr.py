#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JEFFLEBOT (version FR) – Bot Telegram de gestion d'entreprise digitale tout-en-un
-------------------------------------------------------------------------------
Fonctions principales (utilisateurs & admin):
- Commandes clients: passer une commande, panier, paiement, suivi
- Catalogue & stock: produits, entrées/sorties, inventaire, mouvements
- Comptabilité: livre de caisse (recettes/dépenses), solde de trésorerie
- Paie journalière: enregistrement et suivi des paiements journaliers
- Travailleurs du jour: pointage/présence, affectations
- Recrutement: postulations d'emploi (formulaire), gestion de statut
- Annonces: publication/broadcast aux utilisateurs
- Statistiques: commandes/jour & semaine, CA, tickets moyens
- Admin panel: tout gérer depuis des menus inline

Dépendances:
- aiogram>=3.6
- SQLAlchemy>=2.0
- python-dotenv (optionnel)

Exécution locale:
  pip install aiogram SQLAlchemy python-dotenv
  python jefflebot_fr.py
"""
from __future__ import annotations
import asyncio
import csv
import datetime as dt
import os
from enum import Enum
from typing import Optional, List, Dict

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton as IKB,
    InlineKeyboardMarkup as IKM,
    ReplyKeyboardMarkup as RKM,
    KeyboardButton as KB,
    ReplyKeyboardRemove,
    InputFile,
)
from aiogram.client.default import DefaultBotProperties  # ✅ pour aiogram >= 3.7

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, ForeignKey,
    Boolean, Numeric
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

# ---------------------------------------------------------------------------
# Configuration (intégrée comme demandé)
# ---------------------------------------------------------------------------
BOT_TOKEN = "8236506331:AAGqGfGObPuseFANFHcMLytwXi8kgOWLsT4"
ADMIN_CHAT_ID = 7542162173
DB_URL = os.getenv("DB_URL", "sqlite:///jefflebot.db")

# ---------------------------------------------------------------------------
# Base de données (SQLAlchemy)
# ---------------------------------------------------------------------------
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class UserRole(str, Enum):
    CUSTOMER = "customer"
    WORKER = "worker"
    ADMIN = "admin"

class OrderStatus(str, Enum):
    NEW = "NOUVELLE"
    CONFIRMED = "CONFIRMEE"
    PAID = "PAYEE"
    SHIPPED = "EXPEDIEE"
    DONE = "TERMINEE"
    CANCELED = "ANNULEE"

class LedgerType(str, Enum):
    INCOME = "RECETTE"
    EXPENSE = "DEPENSE"

class ShiftStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, index=True)
    first_name = Column(String(128))
    last_name = Column(String(128))
    username = Column(String(128))
    role = Column(String(32), default=UserRole.CUSTOMER.value)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), index=True)
    sku = Column(String(64), unique=True, index=True)
    price = Column(Numeric(12,2), default=0)
    stock_qty = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    qty_change = Column(Integer)
    reason = Column(String(255))
    ref_type = Column(String(64), nullable=True)
    ref_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    product = relationship("Product")

class Cart(Base):
    __tablename__ = "carts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    is_open = Column(Boolean, default=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    user = relationship("User")

class CartItem(Base):
    __tablename__ = "cart_items"
    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer, ForeignKey("carts.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    qty = Column(Integer, default=1)
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    cart = relationship("Cart")
    product = relationship("Product")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    customer_name = Column(String(255))
    status = Column(String(32), default=OrderStatus.NEW.value)
    total = Column(Numeric(12,2), default=0)
    created_at = Column(DateTime, default=dt.datetime.utcnow, index=True)
    user = relationship("User")

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    qty = Column(Integer, default=1)
    unit_price = Column(Numeric(12,2), default=0)
    product = relationship("Product")

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=dt.datetime.utcnow, index=True)
    entry_type = Column(String(16))
    amount = Column(Numeric(12,2))
    currency = Column(String(8), default="XAF")
    description = Column(Text)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)

class Payroll(Base):
    __tablename__ = "payroll"
    id = Column(Integer, primary_key=True)
    worker_id = Column(Integer, ForeignKey("users.id"))
    date = Column(DateTime, default=dt.datetime.utcnow, index=True)
    amount = Column(Numeric(12,2))
    method = Column(String(64), default="cash")
    note = Column(Text)
    worker = relationship("User")

class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True)
    worker_id = Column(Integer, ForeignKey("users.id"))
    date = Column(DateTime, default=dt.datetime.utcnow, index=True)
    status = Column(String(16), default=ShiftStatus.PRESENT.value)
    role = Column(String(128), nullable=True)
    worker = relationship("User")

class JobApplication(Base):
    __tablename__ = "job_applications"
    id = Column(Integer, primary_key=True)
    applicant_name = Column(String(255))
    contact = Column(String(255))
    position = Column(String(255))
    resume = Column(Text)
    status = Column(String(64), default="recu")
    created_at = Column(DateTime, default=dt.datetime.utcnow)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    text = Column(Text)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

Base.metadata.create_all(engine)

def db() -> Session:
    return SessionLocal()

async def get_or_create_user(message: Message) -> User:
    with db() as s:
        u = s.query(User).filter_by(tg_id=message.from_user.id).one_or_none()
        if u:
            return u
        u = User(
            tg_id=message.from_user.id,
            first_name=message.from_user.first_name or "",
            last_name=message.from_user.last_name or "",
            username=message.from_user.username or "",
            role=UserRole.ADMIN.value if message.from_user.id == ADMIN_CHAT_ID else UserRole.CUSTOMER.value,
        )
        s.add(u)
        s.commit()
        return u

def main_menu(is_admin: bool) -> RKM:
    buttons = [
        [KB(text="🛒 Passer une commande"), KB(text="📦 Suivre ma commande")],
        [KB(text="📰 Dernières annonces"), KB(text="👔 Postuler à un emploi")],
    ]
    if is_admin:
        buttons.append([KB(text="🛠️ Admin")])
    return RKM(keyboard=buttons, resize_keyboard=True)

PAGE_SIZE = 6

def paginated_products_keyboard(page: int = 0) -> IKM:
    with db() as s:
        q = s.query(Product).filter_by(is_active=True).order_by(Product.name.asc())
        total = q.count()
        items = q.offset(page * PAGE_SIZE).limit(PAGE_SIZE).all()
    kb = []
    for p in items:
        kb.append([IKB(text=f"➕ {p.name} ({p.price} CFA)", callback_data=f"add:{p.id}")])
    nav = []
    if page > 0:
        nav.append(IKB(text="⬅️", callback_data=f"page:{page-1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(IKB(text="➡️", callback_data=f"page:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([IKB(text="🧺 Voir le panier", callback_data="cart:open")])
    return IKM(inline_keyboard=kb)

def cart_keyboard(cart_id: int) -> IKM:
    with db() as s:
        items = s.query(CartItem).filter_by(cart_id=cart_id).all()
    kb = []
    for it in items:
        kb.append([
            IKB(text=f"➖ {it.product.name}", callback_data=f"cartdec:{it.id}"),
            IKB(text=f"{it.qty}", callback_data="noop"),
            IKB(text=f"➕", callback_data=f"cartinc:{it.id}"),
            IKB(text=f"🗑️", callback_data=f"cartdel:{it.id}"),
        ])
    kb.append([IKB(text="✅ Valider la commande", callback_data="cart:checkout")])
    kb.append([IKB(text="🔙 Continuer achats", callback_data="cart:back")])
    return IKM(inline_keyboard=kb)

def admin_keyboard() -> IKM:
    return IKM(inline_keyboard=[
        [IKB(text="📚 Produits", callback_data="admin:products"), IKB(text="📦 Stock", callback_data="admin:stock")],
        [IKB(text="🧾 Comptabilité", callback_data="admin:ledger"), IKB(text="💰 Paie", callback_data="admin:payroll")],
        [IKB(text="👷 Travailleurs", callback_data="admin:workers"), IKB(text="📰 Annonces", callback_data="admin:posts")],
        [IKB(text="📊 Statistiques", callback_data="admin:stats"), IKB(text="📤 Export CSV", callback_data="admin:export")],
    ])

class JobForm(StatesGroup):
    name = State()
    contact = State()
    position = State()
    resume = State()

class LedgerForm(StatesGroup):
    kind = State()
    amount = State()
    description = State()

class PayrollForm(StatesGroup):
    worker = State()
    amount = State()
    method = State()
    note = State()

class ProductForm(StatesGroup):
    name = State()
    sku = State()
    price = State()
    stock = State()

class StockAdjustForm(StatesGroup):
    product = State()
    qty = State()
    reason = State()

# ✅ Correction ici pour aiogram >= 3.7
bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
router = Router()
dp = Dispatcher()
dp.include_router(router)

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_CHAT_ID

def ensure_open_cart(user_id: int) -> Cart:
    with db() as s:
        c = (
            s.query(Cart)
            .join(User, Cart.user_id == User.id)
            .filter(User.tg_id == user_id, Cart.is_open == True)
            .one_or_none()
        )
        if c:
            return c
        u = s.query(User).filter_by(tg_id=user_id).one()
        c = Cart(user_id=u.id, is_open=True)
        s.add(c)
        s.commit()
        s.refresh(c)
        return c

def cart_total(cart_id: int) -> float:
    with db() as s:
        items = s.query(CartItem).filter_by(cart_id=cart_id).all()
        total = 0.0
        for it in items:
            total += float(it.qty) * float(it.product.price)
        return round(total, 2)

def order_total(order_id: int) -> float:
    with db() as s:
        items = s.query(OrderItem).filter_by(order_id=order_id).all()
        total = 0.0
        for it in items:
            total += float(it.qty) * float(it.unit_price)
        return round(total, 2)

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    u = await get_or_create_user(message)
    await state.clear()
    txt = (
        "<b>Bienvenue!</b>\n\n"
        "Je suis votre assistant de gestion digitale.\n"
        "Utilisez le menu pour passer une commande, suivre une commande, postuler, ou voir les annonces."
    )
    await message.answer(txt, reply_markup=main_menu(is_admin(u.tg_id)))

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Commandes utiles:\n"
        "- /start – menu principal\n"
        "- /catalogue – voir le catalogue produits\n"
        "- /admin – panneau d'administration (admin uniquement)\n"
    )

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé 🚫")
    await message.answer("Panneau d'administration:", reply_markup=admin_keyboard())

@router.message(F.text == "🛠️ Admin")
async def btn_admin(message: Message):
    await cmd_admin(message)

@router.message(F.text == "🛒 Passer une commande")
async def btn_order(message: Message):
    await message.answer("🛍️ Catalogue – choisissez des produits:", reply_markup=paginated_products_keyboard(0))

@router.message(Command("catalogue"))
async def cmd_catalogue(message: Message):
    await btn_order(message)

@router.message(F.text == "📦 Suivre ma commande")
async def btn_track(message: Message):
    await message.answer("Veuillez envoyer l'ID de votre commande (ex: 1024)")

@router.message(F.text.regexp(r"^\d{1,9}$"))
async def track_by_id(message: Message):
    order_id = int(message.text)
    with db() as s:
        o = s.query(Order).filter_by(id=order_id).one_or_none()
    if not o:
        return await message.answer("Commande introuvable.")
    items_txt = []
    with db() as s:
        items = s.query(OrderItem).filter_by(order_id=o.id).all()
    for it in items:
        items_txt.append(f"• {it.product.name} x{it.qty} – {it.unit_price} CFA")
    txt = (
        f"<b>Commande #{o.id}</b>\n"
        f"Statut: <b>{o.status}</b>\n"
        f"Total: <b>{order_total(o.id)} CFA</b>\n\n"
        + "\n".join(items_txt)
    )
    await message.answer(txt)

@router.message(F.text == "📰 Dernières annonces")
async def btn_posts(message: Message):
    with db() as s:
        posts = s.query(Post).order_by(Post.created_at.desc()).limit(5).all()
    if not posts:
        return await message.answer("Aucune annonce pour le moment.")
    for p in posts:
        await message.answer(f"📰 <b>Annonce</b> ({p.created_at:%d/%m/%Y})\n\n{p.text}")

@router.message(F.text == "👔 Postuler à un emploi")
async def btn_job(message: Message, state: FSMContext):
    await state.set_state(JobForm.name)
    await message.answer("Votre nom complet ?", reply_markup=ReplyKeyboardRemove())

@router.message(JobForm.name)
async def job_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(JobForm.contact)
    await message.answer("Votre contact (téléphone / email) ?")

@router.message(JobForm.contact)
async def job_contact(message: Message, state: FSMContext):
    await state.update_data(contact=message.text.strip())
    await state.set_state(JobForm.position)
    await message.answer("Poste visé ?")

@router.message(JobForm.position)
async def job_position(message: Message, state: FSMContext):
    await state.update_data(position=message.text.strip())
    await state.set_state(JobForm.resume)
    await message.answer("CV ou lien (collez une URL, ou décrivez votre expérience) :")

@router.message(JobForm.resume)
async def job_resume(message: Message, state: FSMContext):
    data = await state.get_data()
    with db() as s:
        app = JobApplication(
            applicant_name=data["name"],
            contact=data["contact"],
            position=data["position"],
            resume=message.text.strip(),
        )
        s.add(app)
        s.commit()
    await state.clear()
    await message.answer("Merci ! Votre candidature a été reçue. ✅")
    try:
        await bot.send_message(ADMIN_CHAT_ID, f"Nouvelle postulation: {data['name']} – {data['position']} – {data['contact']}")
    except Exception:
        pass

@router.callback_query(F.data.startswith("page:"))
async def cb_page(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    await call.message.edit_text("🛍️ Catalogue – choisissez des produits:", reply_markup=paginated_products_keyboard(page))
    await call.answer()

@router.callback_query(F.data.startswith("add:"))
async def cb_add(call: CallbackQuery):
    pid = int(call.data.split(":")[1])
    c = ensure_open_cart(call.from_user.id)
    with db() as s:
        p = s.query(Product).filter_by(id=pid, is_active=True).one_or_none()
        if not p:
            await call.answer("Produit indisponible", show_alert=True)
            return
        it = s.query(CartItem).filter_by(cart_id=c.id, product_id=p.id).one_or_none()
        if it:
            it.qty += 1
        else:
            it = CartItem(cart_id=c.id, product_id=p.id, qty=1)
            s.add(it)
        s.commit()
    await call.answer("Ajouté au panier 🧺")

@router.callback_query(F.data == "cart:open")
async def cb_cart_open(call: CallbackQuery):
    c = ensure_open_cart(call.from_user.id)
    with db() as s:
        items = s.query(CartItem).filter_by(cart_id=c.id).all()
    if not items:
        return await call.answer("Panier vide", show_alert=True)
    lines = [f"🧺 <b>Panier</b> – Total: <b>{cart_total(c.id)} CFA</b>"]
    for it in items:
        lines.append(f"• {it.product.name} x{it.qty} – {float(it.product.price)*it.qty} CFA")
    await call.message.edit_text("\n".join(lines), reply_markup=cart_keyboard(c.id))

@router.callback_query(F.data == "cart:back")
async def cb_cart_back(call: CallbackQuery):
    await call.message.edit_text("🛍️ Catalogue – choisissez des produits:", reply_markup=paginated_products_keyboard(0))

@router.callback_query(F.data.startswith("cartinc:"))
async def cb_cart_inc(call: CallbackQuery):
    it_id = int(call.data.split(":")[1])
    with db() as s:
        it = s.query(CartItem).filter_by(id=it_id).one_or_none()
        if not it:
            return await call.answer("Élément introuvable", show_alert=True)
        it.qty += 1
        s.commit()
        c_id = it.cart_id
    await call.message.edit_reply_markup(reply_markup=cart_keyboard(c_id))
    await call.answer("+1")

@router.callback_query(F.data.startswith("cartdec:"))
async def cb_cart_dec(call: CallbackQuery):
    it_id = int(call.data.split(":")[1])
    with db() as s:
        it = s.query(CartItem).filter_by(id=it_id).one_or_none()
        if not it:
            return await call.answer("Élément introuvable", show_alert=True)
        if it.qty > 1:
            it.qty -= 1
            s.commit()
            c_id = it.cart_id
        else:
            c_id = it.cart_id
            s.delete(it)
            s.commit()
    await call.message.edit_reply_markup(reply_markup=cart_keyboard(c_id))
    await call.answer("-1")

@router.callback_query(F.data.startswith("cartdel:"))
async def cb_cart_del(call: CallbackQuery):
    it_id = int(call.data.split(":")[1])
    with db() as s:
        it = s.query(CartItem).filter_by(id=it_id).one_or_none()
        if not it:
            return await call.answer("Élément introuvable", show_alert=True)
        c_id = it.cart_id
        s.delete(it)
        s.commit()
    await call.message.edit_reply_markup(reply_markup=cart_keyboard(c_id))
    await call.answer("Supprimé")

@router.callback_query(F.data == "cart:checkout")
async def cb_cart_checkout(call: CallbackQuery):
    c = ensure_open_cart(call.from_user.id)
    with db() as s:
        items = s.query(CartItem).filter_by(cart_id=c.id).all()
        if not items:
            return await call.answer("Panier vide", show_alert=True)
        u = s.query(User).filter_by(tg_id=call.from_user.id).one()
        o = Order(user_id=u.id, customer_name=u.first_name or u.username or str(u.tg_id))
        s.add(o)
        s.commit()
        total = 0.0
        for it in items:
            item = OrderItem(order_id=o.id, product_id=it.product_id, qty=it.qty, unit_price=it.product.price)
            s.add(item)
            p = s.query(Product).filter_by(id=it.product_id).one()
            p.stock_qty = max(0, (p.stock_qty or 0) - it.qty)
            sm = StockMovement(product_id=p.id, qty_change=-it.qty, reason="vente", ref_type="order", ref_id=o.id)
            s.add(sm)
            total += float(it.qty) * float(p.price)
        o.total = round(total, 2)
        for it in items:
            s.delete(it)
        c.is_open = False
        s.commit()
        order_id = o.id
        order_total_value = o.total
    await call.message.edit_text(
        f"✅ Commande <b>#{order_id}</b> créée !\nTotal: <b>{order_total_value} CFA</b>\n\n"
        "Payez puis envoyez /payer <id_commande> <montant> pour valider le paiement.\n"
        "Ex: <code>/payer 1024 15000</code>"
    )
    await call.answer()
    try:
        await bot.send_message(ADMIN_CHAT_ID, f"🆕 Nouvelle commande #{order_id} – Total {order_total_value} CFA")
    except Exception:
        pass

@router.message(Command("payer"))
async def cmd_payer(message: Message):
    parts = message.text.strip().split()
    if len(parts) != 3:
        return await message.answer("Format: /payer <id_commande> <montant>")
    try:
        order_id = int(parts[1])
        amount = float(parts[2])
    except ValueError:
        return await message.answer("Valeurs invalides.")
    with db() as s:
        o = s.query(Order).filter_by(id=order_id).one_or_none()
        if not o:
            return await message.answer("Commande introuvable.")
        le = LedgerEntry(entry_type=LedgerType.INCOME.value, amount=amount, description=f"Paiement commande #{order_id}", order_id=order_id)
        s.add(le)
        o.status = OrderStatus.PAID.value
        s.commit()
        total = o.total
    await message.answer(f"Merci ! Paiement enregistré pour la commande #{order_id}.\nTotal commande: {total} CFA\nMontant reçu: {amount} CFA")

@router.callback_query(F.data.startswith("admin:"))
async def cb_admin(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("Accès refusé", show_alert=True)
    action = call.data.split(":")[1]
    if action == "products":
        await call.message.edit_text(
            "📚 Produits – commandes rapides:\n"
            "• /addproduct – ajouter un produit\n"
            "• /listproducts – lister\n"
            "• /toggleproduct <sku> – activer/désactiver\n"
            "• /price <sku> <prix> – modifier prix",
            reply_markup=admin_keyboard()
        )
    elif action == "stock":
        await call.message.edit_text(
            "📦 Stock:\n"
            "• /stockin – entrée stock\n"
            "• /stockout – sortie stock\n"
            "• /inventory – inventaire rapide",
            reply_markup=admin_keyboard()
        )
    elif action == "ledger":
        await call.message.edit_text(
            "🧾 Comptabilité:\n"
            "• /recette – ajouter une recette\n"
            "• /depense – ajouter une dépense\n"
            "• /cash – solde de trésorerie",
            reply_markup=admin_keyboard()
        )
    elif action == "payroll":
        await call.message.edit_text(
            "💰 Paie journalière:\n"
            "• /pay – enregistrer une paie\n"
            "• /paylist – paies récentes",
            reply_markup=admin_keyboard()
        )
    elif action == "workers":
        await call.message.edit_text(
            "👷 Travailleurs:\n"
            "• /addworker <tg_id> – définir rôle worker\n"
            "• /presence <tg_id> <PRESENT|ABSENT> [rôle] – pointage\n"
            "• /workers – liste du jour",
            reply_markup=admin_keyboard()
        )
    elif action == "posts":
        await call.message.edit_text(
            "📰 Annonces:\n"
            "• /post – nouvelle annonce\n"
            "• /broadcast – envoyer à tous",
            reply_markup=admin_keyboard()
        )
    elif action == "stats":
        with db() as s:
            today = dt.datetime.utcnow().date()
            start_day = dt.datetime.combine(today, dt.time.min)
            end_day = dt.datetime.combine(today, dt.time.max)
            day_count = s.query(Order).filter(Order.created_at.between(start_day, end_day)).count()
            weekday = today.weekday()
            week_start_date = today - dt.timedelta(days=weekday)
            week_end_date = week_start_date + dt.timedelta(days=6)
            w_start = dt.datetime.combine(week_start_date, dt.time.min)
            w_end = dt.datetime.combine(week_end_date, dt.time.max)
            week_count = s.query(Order).filter(Order.created_at.between(w_start, w_end)).count()
            day_orders = s.query(Order).filter(Order.created_at.between(start_day, end_day)).all()
            ca_day = sum(float(o.total or 0) for o in day_orders)
        await call.message.edit_text(
            f"📊 Statistiques:\n"
            f"Commandes aujourd'hui: <b>{day_count}</b>\n"
            f"Commandes cette semaine: <b>{week_count}</b>\n"
            f"Chiffre d'affaires (aujourd'hui): <b>{round(ca_day,2)} CFA</b>",
            reply_markup=admin_keyboard()
        )
    elif action == "export":
        path1 = export_products_csv()
        path2 = export_orders_csv()
        try:
            await call.message.answer_document(InputFile(path1))
            await call.message.answer_document(InputFile(path2))
        except Exception:
            pass
        await call.answer("Exports générés")

@router.message(Command("addproduct"))
async def cmd_addproduct(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    await state.set_state(ProductForm.name)
    await message.answer("Nom du produit ?")

@router.message(ProductForm.name)
async def pf_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(ProductForm.sku)
    await message.answer("SKU (référence unique) ?")

@router.message(ProductForm.sku)
async def pf_sku(message: Message, state: FSMContext):
    await state.update_data(sku=message.text.strip().upper())
    await state.set_state(ProductForm.price)
    await message.answer("Prix unitaire (CFA) ?")

@router.message(ProductForm.price)
async def pf_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
    except Exception:
        return await message.answer("Prix invalide, essayez encore.")
    await state.update_data(price=round(price,2))
    await state.set_state(ProductForm.stock)
    await message.answer("Stock initial (quantité) ?")

@router.message(ProductForm.stock)
async def pf_stock(message: Message, state: FSMContext):
    try:
        stock = int(message.text)
    except Exception:
        return await message.answer("Quantité invalide, essayez encore.")
    data = await state.get_data()
    with db() as s:
        p = Product(name=data["name"], sku=data["sku"], price=data["price"], stock_qty=stock, is_active=True)
        s.add(p)
        s.commit()
        sm = StockMovement(product_id=p.id, qty_change=stock, reason="stock initial")
        s.add(sm)
        s.commit()
    await state.clear()
    await message.answer("Produit ajouté ✅")

@router.message(Command("listproducts"))
async def cmd_listproducts(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    with db() as s:
        prods = s.query(Product).order_by(Product.is_active.desc(), Product.name.asc()).all()
    if not prods:
        return await message.answer("Aucun produit")
    lines = ["📚 <b>Produits</b>:"]
    for p in prods:
        lines.append(f"• {p.name} ({p.sku}) – {p.price} CFA – Stock: {p.stock_qty} – {'✅' if p.is_active else '🚫'}")
    await message.answer("\n".join(lines))

@router.message(Command("toggleproduct"))
async def cmd_toggleproduct(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    parts = message.text.strip().split()
    if len(parts) != 2:
        return await message.answer("Usage: /toggleproduct <SKU>")
    sku = parts[1].upper()
    with db() as s:
        p = s.query(Product).filter_by(sku=sku).one_or_none()
        if not p:
            return await message.answer("Produit introuvable")
        p.is_active = not p.is_active
        s.commit()
    await message.answer(f"Produit {sku} – {'activé' if p.is_active else 'désactivé'} ✅")

@router.message(Command("price"))
async def cmd_price(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    parts = message.text.strip().split()
    if len(parts) != 3:
        return await message.answer("Usage: /price <SKU> <prix>")
    sku = parts[1].upper()
    try:
        price = float(parts[2].replace(",", "."))
    except Exception:
        return await message.answer("Prix invalide")
    with db() as s:
        p = s.query(Product).filter_by(sku=sku).one_or_none()
        if not p:
            return await message.answer("Produit introuvable")
        p.price = round(price, 2)
        s.commit()
    await message.answer("Prix mis à jour ✅")

@router.message(Command("stockin"))
async def cmd_stockin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    await state.set_state(StockAdjustForm.product)
    await state.update_data(direction="in")
    await message.answer("SKU du produit pour entrée stock ?")

@router.message(Command("stockout"))
async def cmd_stockout(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    await state.set_state(StockAdjustForm.product)
    await state.update_data(direction="out")
    await message.answer("SKU du produit pour sortie stock ?")

@router.message(StockAdjustForm.product)
async def saf_product(message: Message, state: FSMContext):
    sku = message.text.strip().upper()
    with db() as s:
        p = s.query(Product).filter_by(sku=sku).one_or_none()
    if not p:
        return await message.answer("Produit introuvable. Recommencez.")
    await state.update_data(product_id=p.id, sku=sku)
    await state.set_state(StockAdjustForm.qty)
    await message.answer("Quantité ? (entier)")

@router.message(StockAdjustForm.qty)
async def saf_qty(message: Message, state: FSMContext):
    try:
        qty = int(message.text)
    except Exception:
        return await message.answer("Quantité invalide")
    await state.update_data(qty=qty)
    await state.set_state(StockAdjustForm.reason)
    await message.answer("Raison ? (achat fournisseur / ajustement / etc.)")

@router.message(StockAdjustForm.reason)
async def saf_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    pid, qty, direction = data["product_id"], data["qty"], data["direction"]
    reason = message.text.strip()
    if direction == "out":
        qty = -abs(qty)
    else:
        qty = abs(qty)
    with db() as s:
        p = s.query(Product).filter_by(id=pid).one()
        p.stock_qty = (p.stock_qty or 0) + qty
        sm = StockMovement(product_id=pid, qty_change=qty, reason=reason)
        s.add(sm)
        s.commit()
    await state.clear()
    await message.answer("Mouvement enregistré ✅")

@router.message(Command("inventory"))
async def cmd_inventory(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    with db() as s:
        prods = s.query(Product).order_by(Product.name.asc()).all()
    if not prods:
        return await message.answer("Inventaire vide")
    lines = ["📦 <b>Inventaire</b>:"]
    for p in prods:
        lines.append(f"• {p.name} ({p.sku}) – Stock: {p.stock_qty}")
    await message.answer("\n".join(lines))

@router.message(Command("recette"))
async def cmd_recette(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    await state.set_state(LedgerForm.amount)
    await state.update_data(kind=LedgerType.INCOME.value)
    await message.answer("Montant de la <b>RECETTE</b> ? (ex: 15000)")

@router.message(Command("depense"))
async def cmd_depense(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    await state.set_state(LedgerForm.amount)
    await state.update_data(kind=LedgerType.EXPENSE.value)
    await message.answer("Montant de la <b>DEPENSE</b> ? (ex: 8000)")

@router.message(LedgerForm.amount)
async def ledger_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
    except Exception:
        return await message.answer("Montant invalide")
    await state.update_data(amount=round(amount,2))
    await state.set_state(LedgerForm.description)
    await message.answer("Description ?")

@router.message(LedgerForm.description)
async def ledger_desc(message: Message, state: FSMContext):
    data = await state.get_data()
    with db() as s:
        le = LedgerEntry(entry_type=data["kind"], amount=data["amount"], description=message.text)
        s.add(le)
        s.commit()
    await state.clear()
    await message.answer("Écriture comptable ajoutée ✅")

@router.message(Command("cash"))
async def cmd_cash(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    with db() as s:
        inc = s.query(LedgerEntry).filter_by(entry_type=LedgerType.INCOME.value).all()
        exp = s.query(LedgerEntry).filter_by(entry_type=LedgerType.EXPENSE.value).all()
    bal = sum(float(x.amount) for x in inc) - sum(float(x.amount) for x in exp)
    await message.answer(f"💼 Trésorerie actuelle: <b>{round(bal,2)} CFA</b>")

@router.message(Command("pay"))
async def cmd_pay(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    await state.set_state(PayrollForm.worker)
    await message.answer("TG_ID du travailleur ? (laissez vide pour vous-même)")

@router.message(PayrollForm.worker)
async def pr_worker(message: Message, state: FSMContext):
    txt = message.text.strip()
    if txt:
        try:
            tg_id = int(txt)
        except Exception:
            return await message.answer("TG_ID invalide")
    else:
        tg_id = message.from_user.id
    await state.update_data(worker_tg=tg_id)
    await state.set_state(PayrollForm.amount)
    await message.answer("Montant ?")

@router.message(PayrollForm.amount)
async def pr_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
    except Exception:
        return await message.answer("Montant invalide")
    await state.update_data(amount=round(amount,2))
    await state.set_state(PayrollForm.method)
    await message.answer("Méthode ? (cash / mobile / virement)")

@router.message(PayrollForm.method)
async def pr_method(message: Message, state: FSMContext):
    method = message.text.strip().lower()
    if method not in {"cash", "mobile", "virement"}:
        return await message.answer("Choix: cash / mobile / virement")
    await state.update_data(method=method)
    await state.set_state(PayrollForm.note)
    await message.answer("Note (facultatif, tapez - pour passer)")

@router.message(PayrollForm.note)
async def pr_note(message: Message, state: FSMContext):
    data = await state.get_data()
    note = None if message.text.strip() == "-" else message.text.strip()
    with db() as s:
        w = s.query(User).filter_by(tg_id=data["worker_tg"]).one_or_none()
        if not w:
            w = User(tg_id=data["worker_tg"], first_name="", role=UserRole.WORKER.value)
            s.add(w)
            s.commit()
        pa = Payroll(worker_id=w.id, amount=data["amount"], method=data["method"], note=note)
        s.add(pa)
        le = LedgerEntry(entry_type=LedgerType.EXPENSE.value, amount=data["amount"], description=f"Paie {w.tg_id}")
        s.add(le)
        s.commit()
    await state.clear()
    await message.answer("Paie enregistrée ✅")

@router.message(Command("paylist"))
async def cmd_paylist(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    today = dt.datetime.utcnow().date()
    start = dt.datetime.combine(today, dt.time.min)
    end = dt.datetime.combine(today, dt.time.max)
    with db() as s:
        pays = s.query(Payroll).filter(Payroll.date.between(start, end)).all()
    if not pays:
        return await message.answer("Aucune paie aujourd'hui")
    lines = ["💰 <b>Paies du jour</b>:"]
    total = 0.0
    for p in pays:
        lines.append(f"• {p.worker.tg_id} – {p.amount} via {p.method}")
        total += float(p.amount)
    lines.append(f"Total: <b>{round(total,2)} CFA</b>")
    await message.answer("\n".join(lines))

@router.message(Command("addworker"))
async def cmd_addworker(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    parts = message.text.strip().split()
    if len(parts) != 2:
        return await message.answer("Usage: /addworker <tg_id>")
    try:
        tg_id = int(parts[1])
    except Exception:
        return await message.answer("tg_id invalide")
    with db() as s:
        u = s.query(User).filter_by(tg_id=tg_id).one_or_none()
        if not u:
            u = User(tg_id=tg_id, role=UserRole.WORKER.value)
            s.add(u)
        else:
            u.role = UserRole.WORKER.value
        s.commit()
    await message.answer("Travailleur enregistré ✅")

@router.message(Command("presence"))
async def cmd_presence(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    parts = message.text.strip().split()
    if len(parts) < 3:
        return await message.answer("Usage: /presence <tg_id> <PRESENT|ABSENT> [rôle]")
    try:
        tg_id = int(parts[1])
    except Exception:
        return await message.answer("tg_id invalide")
    status = parts[2].upper()
    if status not in {"PRESENT", "ABSENT"}:
        return await message.answer("Statut: PRESENT ou ABSENT")
    role = " ".join(parts[3:]) if len(parts) > 3 else None
    with db() as s:
        u = s.query(User).filter_by(tg_id=tg_id).one_or_none()
        if not u:
            return await message.answer("Utilisateur inconnu – /addworker d'abord")
        sh = Shift(worker_id=u.id, status=status, role=role)
        s.add(sh)
        s.commit()
    await message.answer("Présence enregistrée ✅")

@router.message(Command("workers"))
async def cmd_workers(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    today = dt.datetime.utcnow().date()
    start = dt.datetime.combine(today, dt.time.min)
    end = dt.datetime.combine(today, dt.time.max)
    with db() as s:
        shifts = s.query(Shift).filter(Shift.date.between(start, end)).all()
    if not shifts:
        return await message.answer("Aucun enregistrement aujourd'hui")
    lines = ["👷 <b>Travailleurs du jour</b>:"]
    for sh in shifts:
        lines.append(f"• {sh.worker.tg_id} – {sh.status} – {sh.role or '-'}")
    await message.answer("\n".join(lines))

@router.message(Command("post"))
async def cmd_post(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    text = message.text.partition(" ")[2].strip()
    if not text:
        return await message.answer("Usage: /post <message>")
    with db() as s:
        p = Post(text=text)
        s.add(p)
        s.commit()
    await message.answer("Annonce enregistrée ✅ – /broadcast pour envoyer")

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    with db() as s:
        users = s.query(User).all()
        last_post = s.query(Post).order_by(Post.created_at.desc()).first()
    if not last_post:
        return await message.answer("Aucune annonce à diffuser.")
    sent = 0
    for u in users:
        try:
            await bot.send_message(u.tg_id, f"📰 <b>Annonce</b>\n\n{last_post.text}")
            sent += 1
        except Exception:
            continue
    await message.answer(f"Diffusion terminée. Envoyé à {sent} utilisateurs.")

@router.message(Command("stats")))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Accès refusé")
    with db() as s:
        today = dt.datetime.utcnow().date()
        start_day = dt.datetime.combine(today, dt.time.min)
        end_day = dt.datetime.combine(today, dt.time.max)
        day_orders = s.query(Order).filter(Order.created_at.between(start_day, end_day)).all()
        day_count = len(day_orders)
        ca_day = sum(float(o.total or 0) for o in day_orders)
        weekday = today.weekday()
        week_start_date = today - dt.timedelta(days=weekday)
        week_end_date = week_start_date + dt.timedelta(days=6)
        w_start = dt.datetime.combine(week_start_date, dt.time.min)
        w_end = dt.datetime.combine(week_end_date, dt.time.max)
        week_orders = s.query(Order).filter(Order.created_at.between(w_start, w_end)).all()
        week_count = len(week_orders)
        ca_week = sum(float(o.total or 0) for o in week_orders)
    avg_ticket_day = round(ca_day / day_count, 2) if day_count else 0
    avg_ticket_week = round(ca_week / week_count, 2) if week_count else 0
    await message.answer(
        "📊 <b>Statistiques</b>\n"
        f"Commandes aujourd'hui: <b>{day_count}</b> – CA: <b>{round(ca_day,2)} CFA</b> – Ticket moyen: {avg_ticket_day} CFA\n"
        f"Commandes semaine: <b>{week_count}</b> – CA: <b>{round(ca_week,2)} CFA</b> – Ticket moyen: {avg_ticket_week} CFA\n"
    )

def export_products_csv() -> str:
    path = "products_export.csv"
    with db() as s:
        prods = s.query(Product).order_by(Product.name.asc()).all()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "sku", "price", "stock", "active", "created_at"])
        for p in prods:
            w.writerow([p.id, p.name, p.sku, p.price, p.stock_qty, p.is_active, p.created_at])
    return path

def export_orders_csv() -> str:
    path = "orders_export.csv"
    with db() as s:
        orders = s.query(Order).order_by(Order.created_at.desc()).all()
        items = s.query(OrderItem).all()
    items_by_order: Dict[int, List[OrderItem]] = {}
    for it in items:
        items_by_order.setdefault(it.order_id, []).append(it)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "date", "status", "total", "line"])
        for o in orders:
            lines = []
            for it in items_by_order.get(o.id, []):
                lines.append(f"{it.product_id}:{it.qty}x{it.unit_price}")
            w.writerow([o.id, o.created_at, o.status, o.total, " | ".join(lines)])
    return path

async def main():
    try:
        await bot.send_message(ADMIN_CHAT_ID, "✅ Jefflebot FR en ligne (polling)")
    except Exception:
        pass
    await dp.start_polling(bot)

if __name__ == "__main__":
    import sys
    try:
        import sqlalchemy
    except Exception:
        print("Installez les dépendances: pip install aiogram SQLAlchemy python-dotenv")
        sys.exit(1)
    asyncio.run(main())
