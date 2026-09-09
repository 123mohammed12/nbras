from django.db import migrations


def create_question_bank_roles(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    question_type, _ = ContentType.objects.get_or_create(app_label='question_bank', model='question')
    for codename, name in (
        ('review_question', 'Can review question versions'),
        ('publish_question', 'Can publish question versions'),
        ('retire_question', 'Can retire questions'),
    ):
        Permission.objects.get_or_create(
            content_type=question_type, codename=codename, defaults={'name': name},
        )
    author_codes = {
        'add_question', 'change_question', 'view_question',
        'change_questionversion', 'view_questionversion',
        'add_questionoption', 'change_questionoption', 'view_questionoption',
        'add_questionasset', 'change_questionasset', 'view_questionasset',
    }
    for code in author_codes:
        Permission.objects.get_or_create(
            content_type=question_type,
            codename=code,
            defaults={'name': f"Can {code.replace('_', ' ')}"},
        )
    role_codes = {
        'Question Bank Author': author_codes,
        'Question Bank Reviewer': author_codes | {'review_question'},
        'Question Bank Publisher': author_codes | {'review_question', 'publish_question', 'retire_question'},
    }
    all_permissions = Permission.objects.filter(content_type__app_label='question_bank')
    for group_name, codes in role_codes.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.set(all_permissions.filter(codename__in=codes))
    admin_group, _ = Group.objects.get_or_create(name='Question Bank Admin')
    admin_group.permissions.set(all_permissions)


class Migration(migrations.Migration):
    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('question_bank', '0006_ar10_question_lifecycle'),
    ]

    operations = [
        migrations.RunPython(create_question_bank_roles, migrations.RunPython.noop),
    ]
