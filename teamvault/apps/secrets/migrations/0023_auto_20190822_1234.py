# Generated by Django 2.2.4 on 2019-08-22 12:34

from django.db import migrations


def backfill_last_changed(apps, schema_editor):
    # We can't import the Person model directly as it may be a newer
    # version than this migration expects. We use the historical version.
    Secret = apps.get_model('secrets', 'Secret')
    for secret in Secret.objects.all():
        if secret.current_revision:  # leftovers from a bug
            secret.last_changed = secret.current_revision.created
            secret.save()


class Migration(migrations.Migration):

    dependencies = [
        ('secrets', '0022_secret_last_changed'),
    ]

    operations = [
        migrations.RunPython(backfill_last_changed),
    ]
