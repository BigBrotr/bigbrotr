The following is a draft project specification. I just want you to organize the project specifications I have given you in a clear, detailed, and professional manner. Please note that sensitive or private configuration variables must be entered in the .env file located in the same folder as the Docker Compose file. Analyze the contents of the existing files in detail before generating the new project document. Also analyze the Python nostr-tools library because functions that are already in that library should not be implemented.




This project is in its very early stages. All of the code comes from an old structure of this project. The new structure of the project has now been outlined, as can be seen by examining the structure of the project folder. The project is called BigBrotr, the name refers to one of the possible implementations that can be generated to use the code in src. The implementations are just different folders where you put everything you need to configure all the parameters, the data to be archived, the services to be started, so that you have the implementation and custom use of the source code. BigBrotr is the implementation of full data archiving and continuous monitoring. Another possible implementation could be called LilBrotr, which could basically only archive the most important data for each event, thus removing the storage of tags and content, while leaving all the functionalities as in BigBrotr. This implementation could perhaps provide configurations for less performing services with parameters compatible with low-performance hardware. However, this implementation is very similar to the bigbrotr implementation in terms of architecture and composition, net of differences in parameters and missing events table columns. So for now, let's focus on completing a single implementation, that of bigbrotr.
As regards implementations/<implementation_name>/config/postgres/init, you can consider these files complete, but there is only one view missing that allows you to associate the highest event timestamp associated with that relay for each relay in events_relays. This will be very useful for synchronization services that need to know what the last timestamp analyzed and entered in the database is for each relay that needs to be synchronized. As for the indexes in the init, there may be some useless ones to remove or useful ones to add. The index part can be improved if it is worthwhile.
Speaking of the changes and additions to be made in the src folder, we have the database file inside the core folder, which must contain a database class that uses the bouncer. This means that a brotr class must be implemented in the brotr file in the core folder, which extends the database class and adds all the specific actions to call the main procedures of any implementation, namely the insertion of events, inserting relays, inserting relay metadata. All in batches or individually. Even delete orphans. See the files in the init folder of the bigbrotr implementation. Each implementation must implement these brotr actions because each implementation is a different brotr, i.e., it implements the brotr class, but then it will have the necessary functions and mandatory procedures in the sql files that will operate with specific logic. Therefore, brotr will take the information when it is created from a specific implementation that will dictate the logic and specifications behind the mandatory parameters and functions typical of brotr, in order to standardize each implementation to the brotr object, which is in fact the common interface for implementations. Note that in each implementation in the implementations/<implementation_name>/config folder, there will be a brotr.yaml file that will contain all the specifications to be given to brotr in order to be created.
The brotr class is useful for interfacing with the database. Then, also in the core folder, we will have the files: config.py, log.py, utils.py, service.py. These will be files with classes and functions that can be used by both brotr and the database if necessary, but above all by the services that are implemented and implementable in the src/services folder. Each service will have a dockerfile in the src/docker folder and a config yaml in implementations/<implementation_name>/config/services that will give the specific configurations to the specific service that the implementation wants to use. The mandatory services are: initializer, monitor, (synchronizer or priority_synchronizer). For each service, the idea will be to do what it needs to do using what it needs, logging via a standard in src/core/log.py, taking configurations from a standard in src/core/config.py, using brotr with the specified implementation configurations. 
Each service actually extends a parent service class in src/core/service.py, where this file will contain a parent service class with all the functionalities needed for a service, such as logging, configuration acquisition, status and health, startup and shutdown, and so on, as well as a run function for the service logic. This class can then also be extended by another parent service class, which is a service that runs in a loop. The various services therefore extend one of the two parent classes and then implement the logic within or other logical functions that they can override. It should be noted that the services must also be able to function outside of Docker. In reality, the core/docker services have a specific docker compose file for each of them, precisely because the various implementations have a docker compose where they start postgres, bouncher, torproxy, and all the mandatory services, as well as any optional services.
All services already have an old operating logic, but they interact with the database through an old brotr interface and without a bouncer. The logic of these services must be maintained but updated significantly. The dvm, api, and finder services still need to be implemented, so we can wait a little longer to do so. This is because we need to update many other things before we can think about creating the logic for these new optional services from scratch.

The following is the entire project tree:
vincenzo@Mac bigbrotr % tree
.
├── implementations
│   └── bigbrotr
│       ├── config
│       │   ├── brotr.yaml
│       │   ├── pgbouncer
│       │   │   └── pgbouncer.ini
│       │   ├── postgres
│       │   │   ├── init
│       │   │   │   ├── 00_extensions.sql
│       │   │   │   ├── 01_utility_functions.sql
│       │   │   │   ├── 02_tables.sql
│       │   │   │   ├── 03_indexes.sql
│       │   │   │   ├── 04_integrity_functions.sql
│       │   │   │   ├── 05_procedures.sql
│       │   │   │   ├── 06_views.sql
│       │   │   │   └── 99_verify.sql
│       │   │   └── postgresql.conf
│       │   └── services
│       │       ├── api.yaml
│       │       ├── dvm.yaml
│       │       ├── finder.yaml
│       │       ├── initializer.yaml
│       │       ├── monitor.yaml
│       │       ├── priority_synchronizer.yaml
│       │       └── synchronizer.yaml
│       ├── data
│       │   ├── postgres
│       │   ├── priority_relays.txt
│       │   └── seed_relays.txt
│       └── docker-compose.yaml
├── LICENSE
├── propt.md
├── requirements.txt
└── src
    ├── core
    │   ├── brotr.py
    │   ├── config.py
    │   ├── database.py
    │   ├── log.py
    │   ├── service.py
    │   └── utils.py
    ├── docker
    │   ├── finder.dockerfile
    │   ├── initializer.dockerfile
    │   ├── monitor.dockerfile
    │   ├── priority_synchronizer.dockerfile
    │   └── synchronizer.dockerfile
    └── services
        ├── api.py
        ├── dvm.py
        ├── finder.py
        ├── initializer.py
        ├── monitor.py
        ├── priority_synchronizer.py
        └── synchronizer.py

14 directories, 42 files