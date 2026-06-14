.PHONY: build clean

VERSION := 1.0.0
NAME    := kelvinator-home-comfort
TARBALL := $(NAME)-$(VERSION).tar.gz
RELEASE := release

build:
	@mkdir -p $(RELEASE)
	chmod +x run.sh
	tar czf $(RELEASE)/$(TARBALL) \
		--exclude='__pycache__' \
		--exclude='*.pyc' \
		--exclude='.git*' \
		--exclude='*.tar.gz' \
		--exclude='*.zip' \
		--exclude='$(RELEASE)/' \
		--exclude='Makefile' \
		.
	@echo "✅ Built $(RELEASE)/$(TARBALL)"

clean:
	rm -rf $(RELEASE)
	@echo "🧹 Cleaned $(RELEASE)/"
