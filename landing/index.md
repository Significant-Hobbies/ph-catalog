# PH Catalog

PH Catalog is a resumable local Product Hunt catalogue and analytics experiment. It normalizes public product records into DuckDB, exports verified compressed Parquet snapshots, and preserves provenance for repeatable research.

The public site is a privacy-safe demonstration of the real pipeline. It contains only three original fictional fixtures. The full locally collected catalogue, databases, and analytical snapshots are not published.

## What the pipeline does

- resumes interrupted collection runs;
- resolves aliases and canonical product identities;
- deduplicates records before analysis;
- records provenance and verification state;
- exports Zstandard-compressed Parquet snapshots;
- supports read-only aggregate exploration.

## Public synthetic records

- [Acme Toolkit](https://ph.significanthobbies.com/samples/acme-toolkit.html)
- [Pixelboard](https://ph.significanthobbies.com/samples/pixelboard.html)
- [Quantify](https://ph.significanthobbies.com/samples/quantify.html)

## Source

[Significant-Hobbies/ph-catalog](https://github.com/Significant-Hobbies/ph-catalog)
