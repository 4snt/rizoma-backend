# RELEASE_3_20 = Bioconductor compatível com R 4.4.x
FROM bioconductor/bioconductor_docker:RELEASE_3_20

# Dependências de sistema
RUN apt-get update && apt-get install -y \
    libpq-dev \
    libgsl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Pacotes CRAN
RUN Rscript -e "install.packages(c('RPostgres','DBI','jsonlite','aws.s3','elastic','randomForest','vegan'), repos='https://cloud.r-project.org', quiet=TRUE)"

# Pacotes Bioconductor — DESeq2 e phyloseq são core, os demais adicionais
RUN Rscript -e "BiocManager::install(c('DESeq2','phyloseq','ANCOMBC','Maaslin2','clusterProfiler','SpiecEasi','dada2'), ask=FALSE, update=FALSE)"

# Arquivos de referência taxonômica para DADA2
# SILVA 138.1 (16S) — Zenodo DOI:10.5281/zenodo.4587955
RUN mkdir -p /refs/unite && \
    curl -fsSL --retry 3 \
      "https://zenodo.org/record/4587955/files/silva_nr99_v138.1_train_set.fa.gz" \
      -o /refs/silva_nr99_v138.1_train_set.fa.gz && \
    curl -fsSL --retry 3 \
      "https://zenodo.org/record/4587955/files/silva_species_assignment_v138.1.fa.gz" \
      -o /refs/silva_species_v138.1.fa.gz

# UNITE 10.0 para ITS (formato DADA2) — Zenodo DOI:10.15156/BIO/2959336
# Arquivo menor (~35 MB); baixa somente o fasta de espécies (developer release)
RUN curl -fsSL --retry 3 \
      "https://zenodo.org/record/10403356/files/UNITE_publicrelease_s_all_10.0.fasta.gz" \
      -o /refs/unite/unite_v10_all.fasta.gz || \
    echo "AVISO: download do UNITE falhou — coloque o arquivo em /refs/unite/ manualmente"

WORKDIR /worker
COPY . .

CMD ["Rscript", "worker.R"]
