# database/

Data tables the backend reads (no database server).

| File | From | Used for |
|---|---|---|
| `omim_genemap2.txt` | omim.org `genemap2.txt` | OMIM phenotype numbers, disease names and inheritance per gene |
| `omim_mim2gene.txt` | omim.org `mim2gene.txt` | the gene MIM number (OMIM\*) |

OMIM's files are licensed and not for redistribution, so they are **not in git**:
download them from omim.org (with the lab's licence) and put them here with these
names before running or building the tool. Without them the tool still works, but
does not suggest OMIM numbers or diseases.
