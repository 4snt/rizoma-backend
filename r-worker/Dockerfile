# RELEASE_3_20 = Bioconductor compatível com R 4.4.x
FROM bioconductor/bioconductor_docker:RELEASE_3_20

# Dependências de sistema
RUN apt-get update && apt-get install -y \
    libpq-dev \
    libgsl-dev \
    && rm -rf /var/lib/apt/lists/*

# Pacotes CRAN
RUN Rscript -e "install.packages(c('RPostgres','DBI','jsonlite','aws.s3','elastic','randomForest'), repos='https://cloud.r-project.org', quiet=TRUE)"

# Pacotes Bioconductor — DESeq2 e phyloseq são core, os demais adicionais
RUN Rscript -e "BiocManager::install(c('DESeq2','phyloseq','ANCOMBC','Maaslin2','clusterProfiler','SpiecEasi'), ask=FALSE, update=FALSE)"

WORKDIR /worker
COPY . .

CMD ["Rscript", "worker.R"]
