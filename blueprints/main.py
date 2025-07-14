from flask import Blueprint, render_template, request
from flask_mail import Message
from extensions import mail

main = Blueprint('main', __name__)

@main.route('/')
def home():
    return render_template('home.html')

@main.route('/pricing')
def pricing():
    return render_template('pricing.html')

@main.route('/submit_purchase', methods=['POST'])
def submit_purchase():
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    address = request.form.get('address')
    message = request.form.get('message', '')
    plan = request.form.get('plan')

    msg = Message('New Purchase Request', recipients=['include1iostream2@gmail.com'])
    msg.body = f"""
    New purchase request for {plan} plan:
    Name: {name}
    Email: {email}
    Phone: {phone}
    Address: {address}
    Message: {message}
    """
    try:
        mail.send(msg)
        return 'Success', 200
    except Exception as e:
        return 'Failed to send email', 500