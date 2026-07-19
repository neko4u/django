from django.db import transaction
from django.db.models import Q
from .models import (
    FaultTreeManual, FaultTreeDoc, FaultTreeCategory,
    FaultTreeNode, FaultTreeEdge, FaultTreeComment,
)


# ==================== Manual ====================

def list_manuals():
    return list(FaultTreeManual.objects.all().values('id', 'name', 'description', 'created_at'))


def create_manual(name, description=''):
    manual = FaultTreeManual.objects.create(name=name, description=description)
    return manual_to_dict(manual)


def delete_manual(manual_id):
    FaultTreeManual.objects.filter(id=manual_id).delete()


def manual_to_dict(m):
    return {'id': m.id, 'name': m.name, 'description': m.description, 'created_at': str(m.created_at)}


# ==================== Doc ====================

def list_docs(manual_id=None):
    qs = FaultTreeDoc.objects.all()
    if manual_id:
        qs = qs.filter(manual_id=manual_id)
    return list(qs.values('id', 'manual_id', 'title', 'description', 'created_at', 'updated_at'))


def search_docs(query):
    qs = FaultTreeDoc.objects.filter(
        Q(title__icontains=query) |
        Q(description__icontains=query) |
        Q(nodes__title__icontains=query) |
        Q(nodes__content__icontains=query)
    ).distinct()
    return list(qs.values('id', 'manual_id', 'title', 'description', 'created_at', 'updated_at'))


def create_doc(manual_id, title, description=''):
    doc = FaultTreeDoc.objects.create(
        manual_id=manual_id if manual_id else None,
        title=title,
        description=description
    )
    return doc_to_dict(doc)


def update_doc(doc_id, title=None, description=None):
    doc = FaultTreeDoc.objects.get(id=doc_id)
    if title is not None:
        doc.title = title
    if description is not None:
        doc.description = description
    doc.save()
    return doc_to_dict(doc)


def delete_doc(doc_id):
    FaultTreeDoc.objects.filter(id=doc_id).delete()


def get_doc_graph(doc_id):
    """获取文档的完整图数据（doc + nodes + edges）"""
    doc = FaultTreeDoc.objects.get(id=doc_id)
    nodes_qs = FaultTreeNode.objects.filter(doc_id=doc_id)
    edges_qs = FaultTreeEdge.objects.filter(doc_id=doc_id)

    return {
        'doc': doc_to_dict(doc),
        'nodes': [
            {
                'id': n.id,
                'doc_id': n.doc_id,
                'title': n.title,
                'content': n.content,
                'pos_x': n.pos_x,
                'pos_y': n.pos_y,
                'created_at': str(n.created_at),
                'updated_at': str(n.updated_at),
            }
            for n in nodes_qs
        ],
        'edges': [
            {
                'id': e.id,
                'doc_id': e.doc_id,
                'source_node_id': e.source_node_id,
                'target_node_id': e.target_node_id,
                'label': e.label,
                'created_at': str(e.created_at),
            }
            for e in edges_qs
        ],
    }


def doc_to_dict(d):
    return {
        'id': d.id,
        'manual_id': d.manual_id,
        'title': d.title,
        'description': d.description,
        'created_at': str(d.created_at),
        'updated_at': str(d.updated_at),
    }


# ==================== Node ====================

def list_nodes(doc_id=None):
    qs = FaultTreeNode.objects.all()
    if doc_id:
        qs = qs.filter(doc_id=doc_id)
    return [
        {
            'id': n.id,
            'doc_id': n.doc_id,
            'title': n.title,
            'content': n.content,
            'pos_x': n.pos_x,
            'pos_y': n.pos_y,
            'created_at': str(n.created_at),
            'updated_at': str(n.updated_at),
        }
        for n in qs
    ]


def get_node(node_id):
    n = FaultTreeNode.objects.get(id=node_id)
    return {
        'id': n.id,
        'doc_id': n.doc_id,
        'title': n.title,
        'content': n.content,
        'pos_x': n.pos_x,
        'pos_y': n.pos_y,
        'created_at': str(n.created_at),
        'updated_at': str(n.updated_at),
    }


def create_node(doc_id, title, content='', pos_x=0, pos_y=0):
    node = FaultTreeNode.objects.create(
        doc_id=doc_id,
        title=title,
        content=content,
        pos_x=pos_x,
        pos_y=pos_y,
    )
    return get_node(node.id)


def update_node(node_id, title=None, content=None, pos_x=None, pos_y=None):
    node = FaultTreeNode.objects.get(id=node_id)
    if title is not None:
        node.title = title
    if content is not None:
        node.content = content
    if pos_x is not None:
        node.pos_x = pos_x
    if pos_y is not None:
        node.pos_y = pos_y
    node.save()
    return get_node(node.id)


def delete_node(node_id):
    FaultTreeNode.objects.filter(id=node_id).delete()


# ==================== Edge ====================

def list_edges(doc_id=None):
    qs = FaultTreeEdge.objects.select_related('source_node', 'target_node')
    if doc_id:
        qs = qs.filter(doc_id=doc_id)
    return [
        {
            'id': e.id,
            'doc_id': e.doc_id,
            'source_node_id': e.source_node_id,
            'target_node_id': e.target_node_id,
            'label': e.label,
            'created_at': str(e.created_at),
        }
        for e in qs
    ]


def create_edge(doc_id, source_node_id, target_node_id, label=''):
    edge = FaultTreeEdge.objects.create(
        doc_id=doc_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        label=label,
    )
    return {
        'id': edge.id,
        'doc_id': edge.doc_id,
        'source_node_id': edge.source_node_id,
        'target_node_id': edge.target_node_id,
        'label': edge.label,
        'created_at': str(edge.created_at),
    }


def update_edge(edge_id, label=None, source_node_id=None, target_node_id=None):
    edge = FaultTreeEdge.objects.get(id=edge_id)
    if label is not None:
        edge.label = label
    if source_node_id is not None:
        edge.source_node_id = source_node_id
    if target_node_id is not None:
        edge.target_node_id = target_node_id
    edge.save()
    return {
        'id': edge.id,
        'doc_id': edge.doc_id,
        'source_node_id': edge.source_node_id,
        'target_node_id': edge.target_node_id,
        'label': edge.label,
        'created_at': str(edge.created_at),
    }


def delete_edge(edge_id):
    FaultTreeEdge.objects.filter(id=edge_id).delete()


# ==================== Category ====================

def list_categories(doc_id=None):
    qs = FaultTreeCategory.objects.all()
    if doc_id:
        qs = qs.filter(doc_id=doc_id)
    return list(qs.values('id', 'name', 'parent_id', 'doc_id'))


def create_category(name, doc_id, parent_id=None):
    cat = FaultTreeCategory.objects.create(name=name, doc_id=doc_id, parent_id=parent_id)
    return {'id': cat.id, 'name': cat.name, 'parent_id': cat.parent_id, 'doc_id': cat.doc_id}


# ==================== Comment ====================

def list_comments(node_id=None):
    qs = FaultTreeComment.objects.all()
    if node_id:
        qs = qs.filter(node_id=node_id)
    return list(qs.values('id', 'node_id', 'author', 'content', 'created_at'))


def create_comment(node_id, content, author='anonymous'):
    comment = FaultTreeComment.objects.create(node_id=node_id, content=content, author=author)
    return {
        'id': comment.id,
        'node_id': comment.node_id,
        'author': comment.author,
        'content': comment.content,
        'created_at': str(comment.created_at),
    }
