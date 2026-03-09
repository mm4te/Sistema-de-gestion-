# routes/main.py
from flask import Blueprint, render_template
from models import get_dashboard_data
from routes import login_required

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def index():
    data = get_dashboard_data()
    return render_template('index.html', **data)
