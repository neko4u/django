from django import forms
import bleach


ALLOWED_TAGS = [
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'del',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li',
    'a', 'img', 'span', 'div',
    'pre', 'code', 'blockquote',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'hr',
]
ALLOWED_ATTRS = {
    'a': ['href', 'title', 'target'],
    'img': ['src', 'alt', 'width', 'height'],
    'span': ['style'],
    'div': ['style'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
}


def sanitize_html(value):
    """白名单过滤 HTML，防止 XSS"""
    if not value:
        return ''
    return bleach.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


class ManualForm(forms.Form):
    name = forms.CharField(max_length=255, min_length=1)
    description = forms.CharField(max_length=5000, required=False)

    def clean_name(self):
        return self.cleaned_data['name'].strip()

    def clean_description(self):
        return self.cleaned_data['description'].strip()


class DocForm(forms.Form):
    manual_id = forms.IntegerField(required=False)
    title = forms.CharField(max_length=255, min_length=1)
    description = forms.CharField(max_length=5000, required=False)

    def clean_title(self):
        return self.cleaned_data['title'].strip()


class NodeForm(forms.Form):
    doc_id = forms.IntegerField()
    title = forms.CharField(max_length=255, min_length=1)
    content = forms.CharField(required=False)
    pos_x = forms.FloatField(required=False, initial=0)
    pos_y = forms.FloatField(required=False, initial=0)

    def clean_title(self):
        return self.cleaned_data['title'].strip()

    def clean_content(self):
        return sanitize_html(self.cleaned_data.get('content', ''))


class NodeUpdateForm(forms.Form):
    title = forms.CharField(max_length=255, required=False)
    content = forms.CharField(required=False)
    pos_x = forms.FloatField(required=False)
    pos_y = forms.FloatField(required=False)

    def clean_title(self):
        t = self.cleaned_data.get('title')
        return t.strip() if t else None

    def clean_content(self):
        c = self.cleaned_data.get('content')
        return sanitize_html(c) if c else None


class EdgeForm(forms.Form):
    doc_id = forms.IntegerField()
    source_node_id = forms.IntegerField()
    target_node_id = forms.IntegerField()
    label = forms.CharField(max_length=255, required=False)

    def clean_label(self):
        return self.cleaned_data['label'].strip()


class EdgeUpdateForm(forms.Form):
    label = forms.CharField(max_length=255, required=False)
    source_node_id = forms.IntegerField(required=False)
    target_node_id = forms.IntegerField(required=False)

    def clean_label(self):
        l = self.cleaned_data.get('label')
        return l.strip() if l else None


class CategoryForm(forms.Form):
    name = forms.CharField(max_length=255, min_length=1)
    doc_id = forms.IntegerField()
    parent_id = forms.IntegerField(required=False)

    def clean_name(self):
        return self.cleaned_data['name'].strip()


class CommentForm(forms.Form):
    node_id = forms.IntegerField()
    content = forms.CharField(max_length=5000, min_length=1)
    author = forms.CharField(max_length=255, required=False, initial='anonymous')

    def clean_author(self):
        a = self.cleaned_data.get('author', '')
        return a.strip() or 'anonymous'

    def clean_content(self):
        return self.cleaned_data['content'].strip()
