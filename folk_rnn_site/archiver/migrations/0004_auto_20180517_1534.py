# -*- coding: utf-8 -*-
# Generated by Django 1.11.11 on 2018-05-17 15:34
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('archiver', '0003_event_recording_tuneevent_tunerecording'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='date',
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name='event',
            name='url',
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='recording',
            name='date',
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name='recording',
            name='url',
            field=models.URLField(blank=True, null=True),
        ),
    ]
