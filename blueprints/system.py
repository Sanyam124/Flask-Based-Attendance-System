from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import db, User, Organization, Class, Attendance, ClassTeacher, Subject
from blueprints.auth import login_required
from werkzeug.security import generate_password_hash
import os

system_bp = Blueprint('system', __name__)


@system_bp.route('/system/dashboard')
@login_required(role='admin')
def superadmin_dashboard():
    superadmin_id = session.get('user_id')
    superadmin = User.query.get_or_404(superadmin_id)
    
    total_organizations = Organization.query.count()
    total_principals = User.query.filter_by(role='principal').count()
    
    return render_template('superadmin_dashboard.html', 
                           total_organizations=total_organizations,
                           total_principals=total_principals,
                           admin=superadmin)

@system_bp.route('/system/organizations', methods=['GET', 'POST'])
@login_required(role='admin')
def superadmin_organizations():
    if request.method == 'POST':
        name = request.form.get('name')
        if not name or not name.strip():
            flash("Organization name is required.", "danger")
            return redirect(url_for('system.superadmin_organizations'))
            
        existing = Organization.query.filter_by(name=name.strip()).first()
        if existing:
            flash(f"Organization '{name}' already exists.", "danger")
            return redirect(url_for('system.superadmin_organizations'))
            
        new_org = Organization(name=name.strip())
        db.session.add(new_org)
        db.session.commit()
        flash(f"Organization '{name}' created successfully.", "success")
        return redirect(url_for('system.superadmin_organizations'))
        
    organizations = Organization.query.order_by(Organization.name).all()
    return render_template('superadmin_organizations.html', organizations=organizations)

@system_bp.route('/system/principals', methods=['GET', 'POST'])
@login_required(role='admin')
def superadmin_principals():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        organization_id = request.form.get('organization_id', type=int)
        
        if not all([username, email, password, organization_id]):
            flash("All fields are required.", "danger")
            return redirect(url_for('system.superadmin_principals'))
            
        if User.query.filter_by(email=email).first():
            flash("A user with this email already exists.", "danger")
            return redirect(url_for('system.superadmin_principals'))
            
        org = Organization.query.get(organization_id)
        if not org:
            flash("Invalid Organization selected.", "danger")
            return redirect(url_for('system.superadmin_principals'))
            
        new_principal = User(
            username=username.strip(),
            email=email.strip(),
            password=generate_password_hash(password),
            role='principal',
            is_active=True,
            organization_id=org.id
        )
        db.session.add(new_principal)
        db.session.commit()
        
        flash(f"Principal '{new_principal.username}' created for '{org.name}' successfully.", "success")
        return redirect(url_for('system.superadmin_principals'))
        
    principals = User.query.filter_by(role='principal').order_by(User.username).all()
    organizations = Organization.query.order_by(Organization.name).all()
    return render_template('superadmin_principals.html', principals=principals, organizations=organizations)

@system_bp.route('/system/organizations/delete/<int:org_id>', methods=['POST'])
@login_required(role='admin')
def delete_organization(org_id):
    """
    Hard-delete an organization.
    WHY allowed: Super Admin needs to fully decommission a school that has
    left the platform, removing all its data cleanly.
    WARNING: Also removes all principals, teachers, students, classes, and
    attendance records belonging to that organization.
    """
    org = Organization.query.get_or_404(org_id)
    confirm = request.form.get('confirm_name', '').strip()
    if confirm != org.name:
        flash(f"Confirmation failed. Type the exact organization name to delete.", "danger")
        return redirect(url_for('system.superadmin_organizations'))

    # 1. Remove all Attendance records for this organization (via joining with Class)
    # We join Attendance with Class to filter by organization_id
    Attendance.query.filter(Attendance.class_id.in_(db.session.query(Class.id).filter_by(organization_id=org_id))).delete(synchronize_session=False)

    # 2. Remove all ClassTeacher associations for this organization
    ClassTeacher.query.filter(ClassTeacher.class_id.in_(db.session.query(Class.id).filter_by(organization_id=org_id))).delete(synchronize_session=False)

    # 3. Remove all subjects
    Subject.query.filter_by(organization_id=org_id).delete()

    # 4. Remove all users
    User.query.filter_by(organization_id=org_id).delete()

    # 5. Remove all classes
    Class.query.filter_by(organization_id=org_id).delete()

    # 6. Delete the organization record (final step before folder removal)
    db.session.delete(org)
    db.session.commit()

    # 3. Final removal of face data folder (Bulk)
    from utils import slugify
    from config import KNOWN_FACES_DIR
    org_dir_name = f"org_{slugify(org.name)}"
    org_full_path = os.path.join(KNOWN_FACES_DIR, org_dir_name)
    if os.path.isdir(org_full_path):
        shutil.rmtree(org_full_path, ignore_errors=True)
    
    # Also check for legacy folder org_ID_Name or org_ID
    # migrate_existing_face_data handles the bulk of this, but we clean up here too if needed
    legacy_org_dir1 = os.path.join(KNOWN_FACES_DIR, f"org_{org.id}_{slugify(org.name)}")
    legacy_org_dir2 = os.path.join(KNOWN_FACES_DIR, f"org_{org.id}")
    for d in [legacy_org_dir1, legacy_org_dir2]:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

    db.session.delete(org)
    db.session.commit()
    flash(f"Organization '{org.name}' and all its data have been permanently deleted.", "success")
    return redirect(url_for('system.superadmin_organizations'))

@system_bp.route('/system/principals/delete/<int:principal_id>', methods=['POST'])
@login_required(role='admin')
def delete_principal(principal_id):
    """
    Remove a principal account.
    WHY allowed: When a principal leaves or needs to be replaced, the Super Admin
    can remove the account. Their organization remains intact; only the account is removed.
    All teachers, students, and classes in the org are unaffected.
    """
    principal = User.query.filter_by(id=principal_id, role='principal').first_or_404()
    confirm = request.form.get('confirm_name', '').strip()
    if confirm != principal.username:
        flash("Confirmation failed. Type the exact principal name to remove.", "danger")
        return redirect(url_for('system.superadmin_principals'))

    name = principal.username
    db.session.delete(principal)
    db.session.commit()
    flash(f"Principal '{name}' has been removed. The organization and its data remain intact.", "success")
    return redirect(url_for('system.superadmin_principals'))


# ─────────────────────────────────────────────────────────────────────────────
#  EDIT organization
# ─────────────────────────────────────────────────────────────────────────────

@system_bp.route('/system/organizations/edit/<int:org_id>', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_organization(org_id):
    org = Organization.query.get_or_404(org_id)
    if request.method == 'POST':
        new_name = request.form.get('name', '').strip()
        if not new_name:
            flash("Organization name cannot be empty.", "danger")
            return redirect(url_for('system.edit_organization', org_id=org_id))
        existing = Organization.query.filter(Organization.name == new_name, Organization.id != org_id).first()
        if existing:
            flash(f"An organization called '{new_name}' already exists.", "danger")
            return redirect(url_for('system.edit_organization', org_id=org_id))
        from utils import slugify
        from config import KNOWN_FACES_DIR
        import os
        
        old_dir_name = f"org_{slugify(org.name)}"
        old_path = os.path.join(KNOWN_FACES_DIR, old_dir_name)
        
        org.name = new_name
        db.session.commit()
        
        new_dir_name = f"org_{slugify(new_name)}"
        new_path = os.path.join(KNOWN_FACES_DIR, new_dir_name)
        
        if old_dir_name != new_dir_name and os.path.exists(old_path):
            try:
                os.rename(old_path, new_path)
                # Rebuild encodings if any users were in this org
                from extensions import frs
                frs.rebuild_encodings()
            except Exception as e:

        flash(f"Organization renamed to '{new_name}' successfully.", "success")
        return redirect(url_for('system.superadmin_organizations'))
    return render_template('superadmin_edit_organization.html', org=org)


# ─────────────────────────────────────────────────────────────────────────────
#  EDIT principal
# ─────────────────────────────────────────────────────────────────────────────

@system_bp.route('/system/principals/edit/<int:principal_id>', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_principal(principal_id):
    principal = User.query.filter_by(id=principal_id, role='principal').first_or_404()
    organizations = Organization.query.order_by(Organization.name).all()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        organization_id = request.form.get('organization_id', type=int)

        if not username or not email or not organization_id:
            flash("Name, email, and organization are required.", "danger")
            return render_template('superadmin_edit_principal.html', principal=principal, organizations=organizations)

        existing_email = User.query.filter(User.email == email, User.id != principal_id).first()
        if existing_email:
            flash(f"Email '{email}' is already used by another account.", "danger")
            return render_template('superadmin_edit_principal.html', principal=principal, organizations=organizations)

        org = Organization.query.get(organization_id)
        if not org:
            flash("Invalid organization selected.", "danger")
            return render_template('superadmin_edit_principal.html', principal=principal, organizations=organizations)

        principal.username = username
        principal.email = email
        principal.organization_id = org.id
        if password and len(password) >= 8:
            principal.password = generate_password_hash(password)
        elif password:
            flash("Password must be at least 8 characters (not changed).", "warning")

        db.session.commit()
        flash(f"Principal '{principal.username}' updated successfully.", "success")
        return redirect(url_for('system.superadmin_principals'))
    return render_template('superadmin_edit_principal.html', principal=principal, organizations=organizations)


# ─────────────────────────────────────────────────────────────────────────────
#  EMAIL principal (opens mailto: in browser — no SMTP)
# ─────────────────────────────────────────────────────────────────────────────

@system_bp.route('/system/principals/email/<int:principal_id>')
@login_required(role='admin')
def email_principal(principal_id):
    """
    Opens the Super Admin's email client pre-filled with login info
    for the selected principal. No server-side SMTP is used.
    """
    principal = User.query.filter_by(id=principal_id, role='principal').first_or_404()
    if not principal.email:
        flash(f"Principal '{principal.username}' has no email on file.", "danger")
        return redirect(url_for('system.superadmin_principals'))

    from urllib.parse import quote
    system_name = os.getenv('SYSTEM_NAME', 'Smart Attendance System')
    org_name = principal.organization.name if principal.organization else 'your institution'
    subject = f"{system_name} — Principal Login Information"
    body = (
        f"Hello {principal.username},\n\n"
        f"You have been appointed as Principal for {org_name} on {system_name}.\n\n"
        f"Your login credentials:\n"
        f"  Email (Login): {principal.email}\n"
        f"  Temporary Password: [Set the password when you created the account]\n\n"
        f"Please log in at your earliest convenience and change your password.\n\n"
        f"Best regards,\nSystem Administrator"
    )
    mailto = f"mailto:{principal.email}?subject={quote(subject)}&body={quote(body)}"
    return redirect(mailto)

