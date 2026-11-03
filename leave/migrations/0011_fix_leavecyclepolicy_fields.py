"""
Migration 0011: Fix LeaveCyclePolicy fields that were missing/wrong in 0010.

0010 (hand-written) missed two things from HorillaModel:
  1. `modified_by` FK to AUTH_USER_MODEL — column never created → 500 on list view
  2. `created_by` FK pointed to employee.employee instead of AUTH_USER_MODEL

This migration adds the missing column and corrects the FK target.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leave", "0010_leavecyclepolicy_leavecyclelog"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Add the missing modified_by column
        migrations.AddField(
            model_name="leavecyclepolicy",
            name="modified_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="leavecyclepolicy_modified_by",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Modified By",
            ),
        ),
        # 2. Fix created_by to point at AUTH_USER_MODEL (was employee.employee in 0010)
        migrations.AlterField(
            model_name="leavecyclepolicy",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="leavecyclepolicy_created_by",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Created By",
            ),
        ),
    ]
