import logging
from flask import render_template, request, redirect, url_for, send_file
from sqlalchemy import func
from . import db
from .models import Orthogroup, Gene, Species, Sequence, GeneKeyLookup
import matplotlib.pyplot as plt
import matplotlib
from tempfile import NamedTemporaryFile


# Use Agg backend to avoid issues with Flask
matplotlib.use('Agg')

def register_routes(app):
    """Register all route handlers on the provided Flask app.

    Args:
        app: Flask application instance to attach routes to.
    """
    @app.route('/')
    def index():
        """Render the home page."""
        app.logger.warning('testing warning log')
        print("Index route accessed")
        return render_template('index.html')

    @app.route('/orthogroup/<string:orthogroup_id>')
    def orthogroup(orthogroup_id):
        """Render a single orthogroup detail page.

        Args:
            orthogroup_id: Orthogroup identifier from the URL.

        Returns:
            Rendered orthogroup template.
        """
        orthogroup = db.session.query(Orthogroup).filter_by(orthogroup_id=orthogroup_id).first_or_404()
        return render_template('orthogroup.html', orthogroup=orthogroup)

    @app.route('/orthogroups', methods=['GET', 'POST'])
    def orthogroups():
        """List orthogroups with optional search and pagination.

        Returns:
            Rendered list template with pagination context.
        """
        search_query = request.form.get('search_query', '')
        page = request.args.get('page', 1, type=int)
        per_page = request.form.get('per_page', 10, type=int)

        print(f"Search query: {search_query}")
        print(f"Page: {page}")
        print(f"Per page: {per_page}")

        query = db.session.query(Orthogroup)
        if search_query:
            query = query.filter(Orthogroup.orthogroup_id.ilike(f'%{search_query}%'))

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        orthogroups = pagination.items

        print(f"Orthogroups: {orthogroups}")

        return render_template('orthogroups.html', orthogroups=orthogroups, pagination=pagination, search_query=search_query, per_page=per_page)
    
    @app.route('/gene/<string:gene_id>', methods=['GET'])
    def gene_detail(gene_id):
        """Render a gene detail page by gene ID.

        Args:
            gene_id: Gene identifier from the URL.

        Returns:
            Rendered gene detail template.
        """
        #gene_id = gene_id.lstrip(" ")
        print(f"Gene ID: {gene_id}")
        gene = db.session.query(Gene).join(Sequence).filter_by(gene_id=gene_id).first_or_404()
        # query for gene but joined with sequence table
        for k,v in gene.__dict__.items():
            print(f"{k}: {v}")
        return render_template('gene.html', gene=gene)

    @app.route('/gene/<string:gene_id>/edit', methods=['POST'])
    def edit_gene(gene_id):
        """Update gene metadata based on form inputs.

        Args:
            gene_id: Gene identifier to update.

        Returns:
            Redirect to the updated gene detail page.
        """
        gene = db.session.query(Gene).filter_by(gene_id=gene_id).first_or_404()
        gene.gene_name = request.form.get('gene_name')
        gene.description = request.form.get('gene_description')
        # Update other fields similarly
        db.session.commit()
        return redirect(url_for('gene_detail', gene_id=gene_id))
    
    @app.route('/gene_search', methods=['GET', 'POST'])
    def gene_search():
        """Render a gene search form or search results.

        Returns:
            Gene search form for GET requests, results page for POST queries.
        """
        if request.method == 'POST':
            search_query = request.form.get('search_query')
            # Perform a case-insensitive search
            genes = db.session.query(Gene).filter(Gene.gene_id.ilike(f"%{search_query}%")).all()
            orthogroups = {gene.orthogroup_id: gene for gene in genes}
            return render_template('gene_search_results.html', genes=genes, orthogroups=orthogroups)
        return render_template('gene_search.html')
    
    @app.route('/site-map')
    def site_map():
        """Collect navigable routes for a site map listing.

        Note:
            This function currently gathers links but does not return a response.
        """
        links = []
        for rule in app.url_map.iter_rules():
            # Filter out rules we can't navigate to in a browser
            # and rules that require parameters
            if "GET" in rule.methods and has_no_empty_params(rule):
                url = url_for(rule.endpoint, **(rule.defaults or {}))
                links.append((url, rule.endpoint))
            # links is now a list of url, endpoint tuples
