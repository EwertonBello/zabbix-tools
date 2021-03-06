# encoding=utf8
from controle.gestor_controles import criar_processo
from controle.models.models import *
from ferramentas.migrar_hosts_de_grupos import etapa_adicionar_grupo, etapa_remover_grupo, nova_fase_adicionar_grupo, \
    nova_fase_remover_grupo
from interfaces import *
from interfaces.commom import conectar_mongoengine, conectar_zabbix
from interfaces.web import create_app
from interfaces.web.forms import NovoProcessoForm, AdicionarGrupoHostsForm, RemoverGrupoHostsForm, NovaFaseForm
from zabbix.base import find_hosts_by_hostnames, find_group_by_name
from flask import render_template, flash, redirect, url_for, Request, json, Response


app = create_app()
app.app_context().push()

@app.before_first_request
def setup():
    conectar_mongoengine()


@app.route('/')
def home():
    processos = Processo.objects.all()
    return render_template('processo.html', processos=processos)
    '''NOVO HOME'''

@app.route('/processo')
def processo():
    processos = Processo.objects.all()
    return render_template('processo.html', processos=processos)


@app.route('/inclusao/processo', methods=['GET', 'POST'])
def novo_processo():
    form = NovoProcessoForm()
    if form.validate_on_submit():
        nome = form.nome.data
        descricao = form.descricao.data
        autor = form.email.data

        try:
            processo = criar_processo(nome=nome, descricao=descricao, autor=autor)
        except NotUniqueError:
            flash(u'Erro: já existe um processo com nome {}'.format(nome))
            return redirect(url_for('novo_processo'))

        flash(u'Processo {} criado com sucesso'.format(processo.nome))

        return redirect(url_for('novo_processo'))

    return render_template('novo_processo.html', form=form)


@app.route('/inclusao/<nome_processo>/etapa')
def nova_etapa(nome_processo):
    operacoes = ('adicionar_grupo_hosts', 'remover_grupo_hosts')
    return render_template('nova_etapa.html', nome_processo=nome_processo, operacoes=operacoes)


@app.route('/inclusao/<nome_processo>/etapa/adicionar_grupo_hosts', methods=['GET', 'POST'])
def adicionar_grupo_hosts(nome_processo):
    form = AdicionarGrupoHostsForm()

    if form.validate_on_submit():
        zapi = conectar_zabbix()
        processo = Processo.objects(nome=nome_processo).first()

        lista_hosts = converter_texto_lista_hosts(form.hosts.data)

        hosts = find_hosts_by_hostnames(zapi, lista_hosts)

        hostanames = [h['name'] for h in hosts]

        ignorados = set(lista_hosts).symmetric_difference(set(hostanames))

        group = find_group_by_name(zapi, form.novo_grupo.data)

        nome_etapa = form.nome.data
        descricao = form.descricao.data
        executor_etapa = form.email.data
        novo_grupo = group

        etapa_adicionar_grupo(zapi=zapi, processo=processo, hosts=hosts, nome_etapa=nome_etapa,
                              descricao_etapa=descricao, executor_etapa=executor_etapa, novo_grupo=novo_grupo)

        flash(u'Etapa {} executada com sucesso. Ignorados: {}'.format(nome_etapa, repr(ignorados)))

        return redirect(url_for('adicionar_grupo_hosts', nome_processo=nome_processo))

    return render_template('etapa_adicionar_grupo_hosts.html', form=form)


@app.route('/inclusao/<nome_processo>/etapa/remover_grupo_hosts', methods=['GET', 'POST'])
def remover_grupo_hosts(nome_processo):
    form = RemoverGrupoHostsForm()

    if form.validate_on_submit():
        zapi = conectar_zabbix()
        processo = Processo.objects(nome=nome_processo).first()
        hosts = find_hosts_by_hostnames(zapi, converter_texto_lista_hosts(form.hosts.data))
        group = find_group_by_name(zapi, form.grupo_removido.data)

        nome_etapa = form.nome.data
        descricao = form.descricao.data
        executor = form.email.data
        grupo_removido = group

        etapa_remover_grupo(zapi=zapi, processo=processo, hosts=hosts, nome_etapa=nome_etapa, descricao_etapa=descricao,
                            executor_etapa=executor, grupo_removido=grupo_removido)

        flash(u'Etapa {} executada com sucesso'.format(nome_etapa))

        return redirect(url_for('remover_grupo_hosts', nome_processo=nome_processo))

    return render_template('etapa_remover_grupo_hosts.html', form=form)


@app.route('/processo/etapas/<nome_processo>')
def etapas(nome_processo):

    processo = Processo.objects(nome = nome_processo).first()

    return render_template('etapas.html', processo=processo, etapas=processo.etapas)


@app.route('/processo/etapas/<nome_processo>/<nome_etapa>/detalhes')
def detalhe_etapa(nome_processo, nome_etapa):
    processo = Processo.objects(nome=nome_processo).first()

    etapa = None
    for etapa in processo.etapas:
        if etapa.nome == nome_etapa:
            etapa = etapa
            break

    return render_template('detalhe_etapa.html', etapa=etapa)


@app.route('/inclusao/<nome_processo>/<nome_etapa>/fase', methods=['GET', 'POST'])
def nova_fase(nome_processo, nome_etapa):
    form = NovaFaseForm()

    if form.validate_on_submit():
        zapi = conectar_zabbix()
        processo = Processo.objects(nome=nome_processo).first()

        nome_etapa = nome_etapa

        lista_hosts = converter_texto_lista_hosts(form.hosts.data)

        hosts = find_hosts_by_hostnames(zapi, lista_hosts)

        hostanames = [h['name'] for h in hosts]

        ignorados = set(lista_hosts).symmetric_difference(set(hostanames))

        executor = form.email.data

        etapa_faseada = None
        for etapa in processo.etapas:
            if etapa.nome == nome_etapa:
                etapa_faseada = etapa
                break

        if etapa.atributo_modificado._cls == 'AtributoIncluido':
            nova_fase_adicionar_grupo(zapi=zapi, processo=processo, executor=executor, hosts=hosts, etapa_faseada=etapa_faseada)

        elif etapa.atributo_modificado._cls == 'AtributoExcluido':
            nova_fase_remover_grupo(zapi=zapi, processo=processo, executor=executor, hosts=hosts,
                                      etapa_faseada=etapa_faseada)

        flash(u'Fase executada com sucesso, {} ignorados'.format(repr(ignorados)))

        return redirect(url_for('nova_fase', nome_processo=nome_processo, nome_etapa=nome_etapa))

    return render_template('nova_fase.html', form=form)


@app.route('/_grupo_autocomplete', methods=['GET'])
def grupo_autocomplete():
    grupos = [g['name'] for g in conectar_zabbix().hostgroup.get()]
    return Response(json.dumps(grupos), mimetype='application/json')

def converter_texto_lista_hosts(hostnames):
    hostnames = hostnames.replace(',', '\n')
    hostnames = hostnames.split('\n')
    hostnames = [x.strip() for x in hostnames]
    return hostnames