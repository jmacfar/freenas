# Copyright 2010 iXsystems, Inc.
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#####################################################################
import logging

from croniter import croniter
from dojango import forms
from dojango.forms import ModelForm as MF
from dojango.forms import Form as F

from freenasUI.freeadmin.apppool import appPool
from freenasUI.freeadmin.sqlite3_ha.base import NO_SYNC_MAP

log = logging.getLogger('common.forms')


def mchoicefield(form, field, default):
    """
    Utility method to convert comma delimited field
    """
    if field in form.initial:
        cm = form.initial[field]
    else:
        cm = form.fields[field].initial
    if cm is None:
        cm = '*'
    if cm == '*':
        form.initial[field] = default
    else:
        form.initial[field] = cm.split(',')

    if form.instance.id and any(v in field.split('_') for v in ('dayweek', 'month')):
        index = 4 if 'dayweek' in field else 3

        if cm != '*':
            expression = ''
            for i in range(0, 5):
                expression += ('* ' if i != index else f'{cm} ')
            form.initial[field] = [v or 7 for v in croniter(expression).expanded[index]]


class AdvMixin(object):

    def __init__(self, *args, **kwargs):
        if not hasattr(self, 'advanced_fields'):
            self.advanced_fields = []
        self.parent = kwargs.pop('parent', None)
        super(AdvMixin, self).__init__(*args, **kwargs)

    def isAdvanced(self):
        return len(self.advanced_fields) > 0


class MiddlewareMixin:
    """
    Map middleware attribute names to django form fields.
    This is so we can report errors in the correct field.
    """
    middleware_attr_map = {}
    middleware_attr_prefix = None
    middleware_attr_schema = None


class ModelForm(AdvMixin, MiddlewareMixin, MF):
    """
    We need to handle dynamic choices, mainly because of the FreeNAS_User,
    so we use a custom formfield with a _reroll method which is called
    on every form instantiation
    """

    def __init__(self, *args, **kwargs):
        self._fserrors = {}
        self._api = kwargs.pop('api_validation', False)
        super(ModelForm, self).__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            """
            Only show fields that are node specific in passive node
            e.g. hostname
            """
            table = self.instance._meta.db_table
            nosync = NO_SYNC_MAP.get(table)
            if nosync and 'fields' in nosync:
                from freenasUI.middleware.notifier import notifier
                if (
                    hasattr(notifier, 'failover_status') and
                    notifier().failover_status() == 'BACKUP'
                ):
                    for fname in list(self.fields.keys()):
                        if fname not in nosync['fields']:
                            del self.fields[fname]

        fname = str(type(self).__name__)
        appPool.hook_form_init(fname, self, *args, **kwargs)
        for name, field in list(self.fields.items()):
            if hasattr(field, "_reroll"):
                field._reroll()

    def as_table(self):
        """Returns this form rendered as HTML <tr>s -- excluding the
        <table></table>."""
        return self._html_output(
            normal_row=(
                '<tr%(html_class_attr)s><th>%(label)s</th><td>'
                '%(errors)s%(field)s</td></tr>'
            ),
            error_row='<tr><td colspan="2">%s</td></tr>',
            row_ender='</td></tr>',
            help_text_html='<br />%s',
            errors_on_separate_row=False)

    def clean(self, *args, **kwargs):
        cdata = self.cleaned_data
        """
        Remove leading and trailing spaces from the fields
        See #3252 for why
        """
        for fname, field in list(self.fields.items()):
            val = cdata.get(fname, None)
            if val is None:
                continue
            if (
                isinstance(field.widget, forms.widgets.ValidationTextInput) and
                isinstance(val, str)
            ):
                cdata[fname] = val.strip()
        return cdata

    def delete(self, request=None, events=None, **kwargs):
        self.instance.delete(**kwargs)
        fname = str(type(self).__name__)
        appPool.hook_form_delete(fname, self, request, events)

    def is_valid(self, formsets=None):
        valid = super(ModelForm, self).is_valid()
        if valid is False:
            return valid
        if formsets is not None:
            for name, fsinfo in list(formsets.items()):
                fs = fsinfo['instance']
                methodname = "clean%s" % (name, )
                if hasattr(self, methodname):
                    valid &= getattr(self, methodname)(fs, fs.forms)
        if self._fserrors:
            if '__all__' not in self._errors:
                self._errors['__all__'] = self._fserrors
            else:
                self._errors['__all__'] += self._fserrors
        return valid

    def done(self, request, events):
        fname = str(type(self).__name__)
        appPool.hook_form_done(fname, self, request, events)


class Form(AdvMixin, MiddlewareMixin, F):
    """
    We need to handle dynamic choices, mainly because of the FreeNAS_User,
    so we use a custom formfield with a _reroll method which is called
    on every form instantiation
    """
    def __init__(self, *args, **kwargs):
        self._api = kwargs.pop('api_validation', False)
        super(Form, self).__init__(*args, **kwargs)
        fname = str(type(self).__name__)
        appPool.hook_form_init(fname, self, *args, **kwargs)
        for name, field in list(self.fields.items()):
            if hasattr(field, "_reroll"):
                field._reroll()

    def as_table(self):
        """Returns this form rendered as HTML <tr>s -- excluding the
        <table></table>."""
        return self._html_output(
            normal_row=(
                '<tr%(html_class_attr)s><th>%(label)s</th><td>'
                '%(errors)s%(field)s</td></tr>'
            ),
            error_row='<tr><td colspan="2">%s</td></tr>',
            row_ender='</td></tr>',
            help_text_html='<br />%s',
            errors_on_separate_row=False)

    def done(self, request=None, events=None, **kwargs):
        fname = str(type(self).__name__)
        appPool.hook_form_done(fname, self, request, events)
