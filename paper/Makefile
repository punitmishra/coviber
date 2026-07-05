# Build the CoViber whitepaper.
#
# Requirements: pdflatex + bibtex (any modern TeX distribution).
# Typical macOS install:  brew install --cask mactex-no-gui
# Typical Ubuntu install: sudo apt install texlive-full
#
# Standard three-pass build so cross-refs and citations resolve.

PAPER := whitepaper
BIB   := references

.PHONY: all clean distclean

all: $(PAPER).pdf

$(PAPER).pdf: $(PAPER).tex $(BIB).bib sections/*.tex
	pdflatex -interaction=nonstopmode $(PAPER).tex
	bibtex $(PAPER)
	pdflatex -interaction=nonstopmode $(PAPER).tex
	pdflatex -interaction=nonstopmode $(PAPER).tex

clean:
	rm -f $(PAPER).aux $(PAPER).log $(PAPER).bbl $(PAPER).blg
	rm -f $(PAPER).out $(PAPER).toc $(PAPER).fdb_latexmk $(PAPER).fls
	rm -f $(PAPER).synctex.gz

distclean: clean
	rm -f $(PAPER).pdf
