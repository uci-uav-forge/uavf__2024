# This file is essentally the template file for the actual dockerfile which will be generated by setup_image.py
# Do not change the positioning of anything until after the "---"" line
FROM PLACEHOLDER

# from ardupilot
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install --no-install-recommends -y \
    lsb-release \
    sudo \
    wget \
    software-properties-common \
    build-essential  \
    ccache \
    g++ \ 
    gdb \
    gawk \
    git \
    make \
    cmake \
    ninja-build \
    libtool \
    libxml2-dev \
    libxslt1-dev \
    python3-numpy \
    python3-pyparsing \
    python3-serial \
    python-is-python3 \
    libpython3-stdlib \
    libtool-bin \
    zip \
    default-jre \
    socat \
    ros-dev-tools \
    ros-humble-launch-pytest \
    && apt-get clean \
    && apt-get -y autoremove \
    && apt-get autoclean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# TAKEN from https://github.com/docker-library/python/blob/a58630aef106c8efd710011c6a2a0a1d551319a0/3.11/bullseye/Dockerfile
# if this is called "PIP_VERSION", pip explodes with "ValueError: invalid truth value '<VERSION>'"
ENV PYTHON_PIP_VERSION 23.1.2
# https://github.com/docker-library/python/issues/365
ENV PYTHON_SETUPTOOLS_VERSION 65.5.1
# https://github.com/pypa/get-pip
ENV PYTHON_GET_PIP_URL https://github.com/pypa/get-pip/raw/9af82b715db434abb94a0a6f3569f43e72157346/public/get-pip.py
ENV PYTHON_GET_PIP_SHA256 45a2bb8bf2bb5eff16fdd00faef6f29731831c7c59bd9fc2bf1f3bed511ff1fe

RUN set -eux; \
	\
	wget -O get-pip.py "$PYTHON_GET_PIP_URL"; \
	echo "$PYTHON_GET_PIP_SHA256 *get-pip.py" | sha256sum -c -; \
	\
	export PYTHONDONTWRITEBYTECODE=1; \
	\
	python get-pip.py \
		--disable-pip-version-check \
		--no-cache-dir \
		--no-compile \
		"pip==$PYTHON_PIP_VERSION" \
		"setuptools==$PYTHON_SETUPTOOLS_VERSION" \
	; \
	rm -f get-pip.py; \
	\
	pip --version

RUN python -m pip install --no-cache-dir -U future lxml pexpect flake8 pyelftools tabulate pymavlink pre-commit

FROM eclipse-temurin:19-jdk-jammy as dds-gen-builder

RUN apt-get update && apt-get install --no-install-recommends -y \
    git \
    && apt-get clean \
    && apt-get -y autoremove \
    && apt-get autoclean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN git clone -b develop --recurse-submodules https://github.com/ArduPilot/Micro-XRCE-DDS-Gen.git --depth 1 --no-single-branch --branch develop dds-gen \
    && cd dds-gen \
    && ./gradlew assemble

FROM main-setup

WORKDIR /dds-gen
COPY --from=dds-gen-builder /dds-gen/scripts scripts/
COPY --from=dds-gen-builder /dds-gen/share share/
WORKDIR /

# Get STM32 GCC10 toolchain
ARG ARM_ROOT="gcc-arm-none-eabi-10"
ARG ARM_ROOT_EXT="-2020-q4-major"
ARG ARM_TARBALL="$ARM_ROOT$ARM_ROOT_EXT-x86_64-linux.tar.bz2"
ARG ARM_TARBALL_URL="https://firmware.ardupilot.org/Tools/STM32-tools/$ARM_TARBALL"

RUN cd /opt \
	&& wget -qO- "$ARM_TARBALL_URL" | tar jx \
	&& mv "/opt/$ARM_ROOT$ARM_ROOT_EXT" "/opt/$ARM_ROOT" \
	&& rm -rf "/opt/$ARM_ROOT/share/doc"

# manual ccache setup for arm-none-eabi-g++/arm-none-eabi-gcc
RUN ln -s /usr/bin/ccache /usr/lib/ccache/arm-none-eabi-g++ \
	&& ln -s /usr/bin/ccache /usr/lib/ccache/arm-none-eabi-gcc

# Set STM32 toolchain to the PATH
ENV PATH="/opt/$ARM_ROOT/bin:$PATH"

RUN mkdir -p $HOME/arm-gcc \
    && ln -s -f /opt/gcc-arm-none-eabi-10/ g++-10.2.1


ENV PATH="/dds-gen/scripts:$PATH"
# Set ccache to the PATH
ENV PATH="/usr/lib/ccache:$PATH"

# Gain some time by disabling mavnative
ENV DISABLE_MAVNATIVE=True

# Set the buildlogs directory into /tmp as other directory aren't accessible
ENV BUILDLOGS=/tmp/buildlogs

ENV TZ=UTC

#-------------------------------------p
# EVERYTHING BELOW THIS LINE IS EDITABLE
#-------------------------------------
RUN apt update
RUN apt-get update --fix-missing
RUN apt-get install -y python3-pip
RUN apt-get install -y ffmpeg libsm6 libxext6

WORKDIR "/home/ws/uavf_2024"
COPY setup.py setup.py
RUN pip install -e .

# GNC setup stuff (gazebo garden, ardupilot sitl, and respective ros2 plugins etc)

#RUN echo 'export PATH="$PATH:$HOME/.local/bin"' >> /root/.bashrc
RUN sudo apt-get install -y ros-humble-mavros ros-humble-mavros-extras
RUN bash -ic "source /opt/ros/humble/setup.bash && ros2 run mavros install_geographiclib_datasets.sh"

WORKDIR "/"

RUN git clone https://github.com/PX4/PX4-Autopilot.git --recursive
RUN bash ./PX4-Autopilot/Tools/setup/ubuntu.sh



RUN apt-get remove modemmanager -y
RUN apt install gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-gl -y
RUN apt install libqt5gui5 -y
RUN apt install libfuse2 -y
RUN apt install libpulse-mainloop-glib0 -y
RUN wget "https://d176tv9ibo4jno.cloudfront.net/latest/QGroundControl.AppImage"
RUN chmod a+x /QGroundControl.AppImage
RUN useradd qgc
RUN usermod -a -G dialout qgc

# Sourcing script at runtime
COPY .devcontainer/bashrc_setup.sh /usr/local/bin/bashrc_setup.sh
RUN chmod 777 /usr/local/bin/bashrc_setup.sh
RUN /usr/local/bin/bashrc_setup.sh

CMD ["/bin/bash"]
