from glob import glob

from setuptools import find_packages, setup

package_name = 'self_compention_tof'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/dataset', sorted(glob('dataset/*.txt'))),
    ],
    install_requires=['setuptools', 'matplotlib', 'numpy', 'scipy'],
    zip_safe=True,
    maintainer='song',
    maintainer_email='dudqls10@g.skku.edu',
    description='ToF self-reference model builder and replay classifier for RB10 datasets.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'plot_distance_txt = my_package.plot_distance_txt:main',
            'build_tof_self_model = self_compention_tof.build_self_model:main',
            'replay_tof_classifier = self_compention_tof.replay_classifier:main',
            'plot_tof_replay = self_compention_tof.plot_replay:main',
            'realtime_tof_self_infer = self_compention_tof.realtime_infer_node:main',
        ],
    },
)
