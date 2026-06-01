# bioconductor_docker inclui R 4.4 + DESeq2 + phyloseq + edgeR + limma pré-compilados
FROM bioconductor/bioconductor_docker:RELEASE_3_19

# Dependências de sistema
RUN apt-get update && apt-get install -y \
    libpq-dev \
    libgsl-dev \
    && rm -rf /var/lib/apt/lists/*

# Pacotes CRAN não incluídos na imagem base
RUN Rscript -e "install.packages(c('RPostgres','DBI','jsonlite','aws.s3','elastic','randomForest'), repos='https://cloud.r-project.org', quiet=TRUE)"

# Pacotes Bioconductor (binários pré-compilados disponíveis no repositório container-binaries)
RUN Rscript -e "BiocManager::install(c('DESeq2','phyloseq','ANCOMBC','Maaslin2','clusterProfiler','SpiecEasi'), ask=FALSE, update=FALSE)"

WORKDIR /worker
COPY . .

CMD ["Rscript", "worker.R"]
