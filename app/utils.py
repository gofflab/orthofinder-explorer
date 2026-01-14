#!/usr/bin/env python

################
# File parsers
################
# Generator for Multiple-sequence fasta parser
def fasta_generator(fasta_file):
    """Yield FASTA headers and sequences from a file path.

    Args:
        fasta_file: Path to a multi-sequence FASTA file.

    Yields:
        Tuples of (header, sequence) with the leading '>' preserved in header.
    """
    with open(fasta_file) as f:
        header = None
        sequence = ''
        for line in f:
            if line.startswith('>'):
                if header:
                    yield header, sequence
                header = line.strip()
                sequence = ''
            else:
                sequence += line.strip()
        yield header, sequence

# Generator for Gff3 parsing
def gff3_generator(gff3_file):
    """Yield parsed GFF3 rows from a file path.

    Args:
        gff3_file: Path to a GFF3 file.

    Yields:
        List of tab-separated fields for each non-comment line.
    """
    with open(gff3_file) as f:
        for line in f:
            if line.startswith('#'):
                continue
            line = line.strip().split('\t')
            yield line
