# Generated migration for LeaveCyclePolicy and LeaveCycleLog models

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0001_initial'),
        ('employee', '0001_initial'),
        ('leave', '0009_alter_availableleave_is_active_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='LeaveCyclePolicy',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True, verbose_name='Active')),
                ('created_at', models.DateTimeField(auto_now_add=True, null=True, verbose_name='Created At')),
                ('cycle_number', models.CharField(
                    choices=[
                        ('1', 'Cycle 1 (Apr\u2013Jul)'),
                        ('2', 'Cycle 2 (Aug\u2013Nov)'),
                        ('3', 'Cycle 3 (Dec\u2013Mar)'),
                        ('annual', 'Annual (Year Start)'),
                    ],
                    max_length=10,
                    verbose_name='Cycle',
                )),
                ('credit_month', models.IntegerField(
                    choices=[(4, 'April'), (8, 'August'), (12, 'December')],
                    verbose_name='Credit Month',
                )),
                ('credit_day', models.IntegerField(default=1, verbose_name='Credit Day')),
                ('days_to_credit', models.FloatField(verbose_name='Days to Credit')),
                ('carryforward_percent', models.FloatField(
                    default=0.0,
                    help_text='0 = no carry forward, 100 = full, 50 = half. Applied at year-end (31 Mar).',
                    verbose_name='Carry Forward %',
                )),
                ('company_id', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to='base.company',
                    verbose_name='Company',
                )),
                ('leave_type_id', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='leave.leavetype',
                    verbose_name='Leave Type',
                )),
                ('created_by', models.ForeignKey(
                    blank=True,
                    editable=False,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='%(app_label)s_%(class)s_created_by',
                    to='employee.employee',
                    verbose_name='Created By',
                )),
            ],
            options={
                'verbose_name': 'Leave Cycle Policy',
                'verbose_name_plural': 'Leave Cycle Policies',
                'unique_together': {('company_id', 'leave_type_id', 'cycle_number')},
            },
        ),
        migrations.CreateModel(
            name='LeaveCycleLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('leave_year', models.CharField(max_length=10, verbose_name='Leave Year')),
                ('cycle_number', models.CharField(max_length=10, verbose_name='Cycle')),
                ('days_credited', models.FloatField(verbose_name='Days Credited')),
                ('credited_on', models.DateField(verbose_name='Credit Date')),
                ('source', models.CharField(
                    choices=[('scheduler', 'Scheduler'), ('manual', 'Manual')],
                    default='scheduler',
                    max_length=20,
                    verbose_name='Source',
                )),
                ('note', models.TextField(blank=True, verbose_name='Note')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('employee_id', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='employee.employee',
                    verbose_name='Employee',
                )),
                ('leave_type_id', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='leave.leavetype',
                    verbose_name='Leave Type',
                )),
                ('policy_id', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='leave.leavecyclepolicy',
                    verbose_name='Policy',
                )),
            ],
            options={
                'verbose_name': 'Leave Cycle Log',
                'verbose_name_plural': 'Leave Cycle Logs',
                'ordering': ['-credited_on'],
            },
        ),
        migrations.AddConstraint(
            model_name='leavecyclelog',
            constraint=models.UniqueConstraint(
                fields=['employee_id', 'leave_type_id', 'leave_year', 'cycle_number'],
                name='unique_leave_cycle_credit',
            ),
        ),
    ]
