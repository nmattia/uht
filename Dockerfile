FROM micropython/unix@sha256:5eb87acc22007cfb4001ddb498357bcf65cd858e7a8b274718526f261089c7fd

# Libs needed by either the lib or the test suite
RUN micropython -m mip install logging
RUN micropython -m mip install unittest
