//const { selection } = require("d3");

/**
 * Render an interactive phylogenetic tree with species coloring and gene links.
 *
 * @param {string} newickData - Newick-formatted tree string.
 * @param {number} width - SVG width in pixels.
 * @param {number} height - SVG height in pixels.
 * @param {Object} options - Render options.
 * @returns {Object} Rendered phylotree instance.
 */
function createTreeUpdated(newickData, width = 1200, height = 2400, options = {}) {
    const defaultOptions = {
        fontSize: 15,
        tipSpacing: null,
        autoHeight: false,
        branchScale: 1,
        alignTips: true,
        zoom: false,
        speciesColorMap: null,
    };
    const config = Object.assign({}, defaultOptions, options);
    // Define a fallback color mapping for species
    const defaultSpeciesColorMap = {
        // Closely related Caenorhabditis species
        'Caenorhabditis_remanei': '#1f77b4',
        'Caenorhabditis_elegans': '#aec7e8',
    
        // Hofstenia miamia
        'Hofstenia_miamia': '#ff7f0e',
    
        // Closely related Hydra and Amphimedon
        'Hydra_vulgaris': '#2ca02c',
        'Amphimedon_queenslandica': '#98df8a',
    
        // Drosophila melanogaster
        'Drosophila_melanogaster': '#d62728',
    
        // Closely related teleost fish
        'Danio_rerio': '#bcbd22',
        'Salmo_salar': '#dbdb8d',
        'Oncorhynchus_tshawytscha': '#bcbd22',
    
        // Closely related mammals
        'Mus_musculus': '#9467bd',
        'Homo_sapiens': '#c5b0d5',
    
        // Aplysia californica
        'Aplysia_californica': '#ff9896',
    
        // Closely related mollusks
        'Mercenaria_mercenaria': '#8c564b',
        'Crassostrea_virginica': '#c49c94',
        'Mizuhopecten_yessoensis': '#e377c2',
    
        // Closely related octopuses
        'Octopus_bimaculoides': '#174e6f',
        'Octopus_chierchiae': '#0e3a65',
        'Octopus_sinensis': '#17becf',
    
        // Closely related Euprymna and Doryteuthis
        'Euprymna_berryi': '#177e2f',
        'Doryteuthis_pealeii': '#2ca02c'
    };
    const speciesColorMap = config.speciesColorMap || defaultSpeciesColorMap;
    
    // Create a new phylotree
    const tree = new phylotree.phylotree(newickData);

    //Select the SVG element
    const svg = d3.select("#tree-container");

    // Clear previous content
    svg.selectAll("*").remove();

    const tipCount = tree.getTips().length;
    let renderHeight = height;
    if (config.autoHeight && config.tipSpacing) {
        renderHeight = (tipCount * config.tipSpacing) + 200;
    }
    const renderWidth = width * config.branchScale;

    // Set the dimensions of the SVG
    svg.attr("width", renderWidth).attr("height", renderHeight);

    // Get an array of all genus names from node names.split("_")[0]
    /**
     * Extract unique genus names from tree tip labels.
     *
     * @param {Array} nodeData - Array of tip nodes from phylotree.
     * @returns {Array} Unique genus names.
     */
    getGenusNames = function (nodeData) {
        let selection_set = new Set();

        // Collect genus names from each tip label.
        nodeData.forEach( function(d,i) {
            selection_set.add(d.data.name.split ("_")[0]);
        })
        return Array.from(selection_set);
    };

    selection_set = getGenusNames(tree.getTips());
    //console.log(selection_set);


    // Color by genus
    color_scale = d3.scaleOrdinal(d3.schemeCategory10);
    //selection_set = tree.get_parsed_tags().length > 0 ? tree.get_parsed_tags() : ["Octopus","Salmo","Danio","Homo","Mus"];
    /**
     * Apply a species-based fill color to a node element.
     *
     * @param {Object} element - DOM element for the node.
     * @param {Object} data - Node data from phylotree.
     */
    nodeColorizer = function (element, data) {
        // try{
        //     var count_class = 0;
        //     selection_set.forEach (function (d,i) { 
        //         if (data.data.name.startsWith(d)) { count_class ++; element.style ("fill", color_scale(i), 'important');}
        //     });
        //     if (count_class > 1) {
        
        //     } else {
        //         if (count_class == 0) {
        //             element.style ("fill", null);
        //         }
        //     }
        // }
        const name_parts = data.data.name.split("_");
        const genus = name_parts[0];
        const species = name_parts[1];
        const speciesName = genus + "_" + species;
        const color = speciesColorMap[speciesName] || "#888888";
        element.style ("fill", color, 'important');
        };

    /**
     * Style nodes and attach click navigation for gene detail pages.
     *
     * @param {Object} element - DOM element for the node.
     * @param {Object} data - Node data from phylotree.
     */
    styleNodes = function (element, data) {
        //color nodes by genus name
        nodeColorizer (element, data);
        
        //parse data from gene_name string
        var name_arr = data.data.name.split("_")
        data.data.species = name_arr.slice(0,2).join("_")
        name_arr.splice(0, 2);
        var gene_id = name_arr.join("_")
        if (gene_id.startsWith("gert_")) {
            gene_id = gene_id.slice(5);
        }
        if (gene_id.startsWith("Dpe") && gene_id.includes("__")) {
            gene_id = gene_id.replace(/__([^_]+)__/g, "_[$1]_");
        }
        data.data.gene_id = gene_id
        var url = "/gene/" + gene_id; 
        //var url = "/gene/%20" + gene_id;
        data.data.url = url 
        //console.log({'species': data.data.species, 'gene_id': data.data.gene_id, 'url': data.data.url})

        // Add click handler to open the gene detail page.
        element.on("click", function() {
            window.open(url, "_self")
        });

    };

    // Render the tree
    renderedTree = tree.render({
        container: "#tree-container",
        height:renderHeight,
        width:renderWidth,
        'left-right-spacing': 'fit-to-size', 
        'top-bottom-spacing': 'fit-to-size',
        'node-styler': styleNodes,
        'align-tips': config.alignTips,
        'zoom': config.zoom,
        'show-scale':true,
        // 'minimum-per-level-spacing': 15,
        // 'minimum-per-node-spacing': 15,
        'font-size': config.fontSize,

    })

    $(tree.display.container).html(tree.display.show());
    //console.log('Rendering Tree')

    return tree;
}

/**
 * Render a basic phylotree layout using the legacy d3 layout API.
 *
 * @param {string} newickData - Newick-formatted tree string.
 * @param {number} width - SVG width in pixels.
 * @returns {Object} Rendered tree instance.
 */
function createTree(newickData, width=600) {
    // Clear the existing tree if present
    //d3.select("#tree-container").html("");

    // Initialize the phylotree
    var tree = new d3.layout.phylotree()
        .svg(d3.select("#tree-container"));
        
    tree(d3.layout.newick_parser(newickData)).layout();

    // Update the SVG width
    d3.select("#tree-container svg")
        .attr("width", width)
        .attr("height", tree.size()[1]);

    // Apply styling to the tree
    // tree.style_edges(function(element, data) {
    //     d3.select(element).style("stroke", "black");
    // });

    // tree.style_nodes(function(element, data) {
    //     d3.select(element).select("text").style("font-size", 50);
    // });
    
    // Placeholder hook for per-node inspection or styling.
    tree.get_nodes().forEach (function (tree_node) {
        //console.log(tree_node);
        //tree_node.style("color","red")
    });
    
    // Toggle between layout modes when controls change.
    $(".phylotree-layout-mode").on ("change", function (e) {
        if ($(this).is(':checked')) {
            if (tree.radial () != ($(this).data ("mode") == "radial")) {
                tree.radial (!tree.radial ()).placenodes().update ();
            }
        }
    });
    return tree;
};
